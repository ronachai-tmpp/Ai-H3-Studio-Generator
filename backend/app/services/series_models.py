"""โมเดลข้อมูลและการตรวจสอบของ Series Runner (ไม่มี I/O)"""

from __future__ import annotations

import re
import secrets
import unicodedata
from typing import Literal

from pydantic import BaseModel

from app.services.workflow_service import ALLOWED_ASPECT_RATIOS

ALLOWED_DURATIONS = (5, 8, 10, 12, 15)
ALLOWED_MEGAPIXELS = (0.1, 0.25, 0.35, 0.5, 0.75, 1.0)
DEFAULT_ASPECT_RATIO = "9:16 (Portrait Widescreen)"
DEFAULT_MEGAPIXELS = 0.35
DEFAULT_MAX_ATTEMPTS = 2
MAX_SCENES_PER_EPISODE = 20
MAX_REF_IMAGES_PER_SCENE = 9
CASTING_DURATION_SECONDS = 5


class SeriesError(ValueError):
    """ข้อผิดพลาดของ Series — ข้อความเป็นภาษาไทย ส่งต่อให้ผู้ใช้ได้เลย"""


class RefImage(BaseModel):
    path: str  # relative กับ OUTPUTS_DIR
    comfy_name: str | None = None
    comfy_base_url: str | None = None


class Character(BaseModel):
    name: str
    description: str = ""
    reference_images: list[RefImage] = []
    casting_prompt: str | None = None
    casting_job_id: str | None = None
    casting_attempts: int = 0


class Scene(BaseModel):
    index: int
    prompt: str
    beat: str = ""
    mode: Literal["text", "ref", "chain"]
    characters: list[str] = []
    duration_seconds: int = 5
    seed: int = -1
    status: Literal["PENDING", "QUEUED", "RUNNING", "DONE", "FAILED"] = "PENDING"
    job_id: str | None = None
    attempts: int = 0
    progress: int = 0
    error: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    last_frame_path: str | None = None
    started_at: float | None = None  # epoch seconds
    finished_at: float | None = None


class Episode(BaseModel):
    number: int
    title: str
    synopsis: str = ""
    caption: str = ""
    hashtags: list[str] = []
    status: Literal["PENDING", "RUNNING", "DONE"] = "PENDING"
    scenes: list[Scene]
    final_video_path: str | None = None
    thumbnail_path: str | None = None
    duration: float | None = None


class Series(BaseModel):
    id: str
    title: str
    logline: str = ""
    style_notes: str = ""
    aspect_ratio: str = DEFAULT_ASPECT_RATIO
    megapixels: float = DEFAULT_MEGAPIXELS
    low_vram: bool = False
    run_mode: Literal["autopilot", "review"] = "autopilot"
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    status: Literal["DRAFT", "RUNNING", "PAUSED", "DONE", "CANCELLED"] = "DRAFT"
    pause_reason: Literal["user", "review", "casting", "error"] | None = None
    pause_message: str | None = None
    story_complete: bool = False
    characters: list[Character] = []
    episodes: list[Episode] = []
    created_at: float
    updated_at: float


_JOB_TYPES = {"text": "T2V", "ref": "REF2VA", "chain": "FL2VA"}


def slugify(text: str) -> str:
    """แปลงเป็น a-z0-9 กับ "-" เท่านั้น (อักษรที่ไม่ใช่ ASCII ถูกตัดทิ้ง) อาจคืนสตริงว่าง"""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def new_series_id(title: str) -> str:
    """สร้างรหัส "<slug>-<6 hex>"; ถ้า slug ว่างใช้ "series" แทน"""
    slug = slugify(title)[:40].strip("-") or "series"
    return f"{slug}-{secrets.token_hex(3)}"


def job_type_for(mode: str, low_vram: bool) -> str:
    """ชนิดงานในคิวของแต่ละ mode (T2V / REF2VA / FL2VA, เติม _LOW เมื่อ low_vram)"""
    job_type = _JOB_TYPES[mode]
    return f"{job_type}_LOW" if low_vram else job_type


def needs_casting(character: Character) -> bool:
    """ตัวละครที่ยังไม่มีรูป แต่มี casting_prompt (รอสร้างรูปอ้างอิง)"""
    return not character.reference_images and bool(character.casting_prompt)


def find_character(series: Series, name: str) -> Character | None:
    for character in series.characters:
        if character.name == name:
            return character
    return None


def validate_series(series: Series) -> list[str]:
    """ตรวจ Series ทั้งก้อน คืนรายการข้อความผิดพลาด ([] = ผ่าน)"""
    errors: list[str] = []

    if series.aspect_ratio not in ALLOWED_ASPECT_RATIOS:
        errors.append(
            f"aspect_ratio '{series.aspect_ratio}' ไม่รองรับ "
            f"(ใช้ได้: {sorted(ALLOWED_ASPECT_RATIOS)})"
        )
    if round(series.megapixels, 2) not in ALLOWED_MEGAPIXELS:
        errors.append(
            f"megapixels {series.megapixels} ไม่รองรับ (ใช้ได้: {list(ALLOWED_MEGAPIXELS)})"
        )

    names = [c.name for c in series.characters]
    for name in sorted({n for n in names if names.count(n) > 1}):
        errors.append(f"ชื่อตัวละคร '{name}' ซ้ำกัน")

    for episode_pos, episode in enumerate(series.episodes):
        label = f"ตอนที่ {episode.number}"
        count = len(episode.scenes)
        if not 1 <= count <= MAX_SCENES_PER_EPISODE:
            errors.append(f"{label}: ต้องมี 1-{MAX_SCENES_PER_EPISODE} ฉาก (มี {count})")

        for position, scene in enumerate(episode.scenes, start=1):
            where = f"{label} ฉากที่ {position}"
            if not scene.prompt.strip():
                errors.append(f"{where}: prompt ว่าง")
            if scene.duration_seconds not in ALLOWED_DURATIONS:
                errors.append(
                    f"{where}: ความยาว {scene.duration_seconds} วินาทีไม่รองรับ "
                    f"(ใช้ได้: {list(ALLOWED_DURATIONS)})"
                )
            if scene.mode == "chain" and episode_pos == 0 and position == 1:
                errors.append(f"{where}: ฉากแรกของเรื่องใช้ mode chain ไม่ได้ (ไม่มีฉากก่อนหน้า)")
            if scene.mode == "ref":
                errors.extend(_validate_ref_scene(series, scene, where))

    return errors


def _validate_ref_scene(series: Series, scene: Scene, where: str) -> list[str]:
    if not scene.characters:
        return [f"{where}: mode ref ต้องระบุตัวละครอย่างน้อย 1 ตัว"]
    errors: list[str] = []
    image_total = 0
    for name in scene.characters:
        character = find_character(series, name)
        if character is None:
            errors.append(f"{where}: ไม่พบตัวละคร '{name}'")
        elif character.reference_images:
            image_total += len(character.reference_images)
        elif character.casting_prompt:
            image_total += 1  # รอ casting จะได้ 1 รูป
        else:
            errors.append(f"{where}: ตัวละคร '{name}' ไม่มีรูปอ้างอิงและไม่มี casting_prompt")
    if image_total > MAX_REF_IMAGES_PER_SCENE:
        errors.append(
            f"{where}: รูปอ้างอิงรวม {image_total} รูป เกินขีดจำกัด "
            f"{MAX_REF_IMAGES_PER_SCENE} รูปต่อฉาก"
        )
    return errors


def waiting_for(series: Series) -> str | None:
    """"episodes" เมื่อกำลังรัน ทุกตอนเสร็จแล้ว แต่เรื่องยังไม่จบ (รอตอนใหม่)"""
    if (
        series.status == "RUNNING"
        and not series.story_complete
        and all(e.status == "DONE" for e in series.episodes)
    ):
        return "episodes"
    return None


def progress_of(series: Series) -> dict:
    scenes = [s for e in series.episodes for s in e.scenes]
    done = [s for s in scenes if s.status == "DONE"]
    durations = [
        s.finished_at - s.started_at
        for s in done
        if s.started_at is not None and s.finished_at is not None
    ]
    avg = sum(durations) / len(durations) if durations else None
    remaining = len(scenes) - len(done)
    return {
        "scenes_done": len(done),
        "scenes_total": len(scenes),
        "avg_scene_seconds": avg,
        "eta_seconds": avg * remaining if avg is not None else None,
    }
