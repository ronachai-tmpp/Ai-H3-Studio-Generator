"""การแก้ไข Series (สร้าง ตัวละคร ตอน ฉาก ควบคุม) — ทุกการแก้ผ่าน validate_series และ lock ของ store"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from app.services.series_gateway import StudioGateway
from app.services.series_models import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MEGAPIXELS,
    Character,
    Episode,
    RefImage,
    Scene,
    Series,
    SeriesError,
    find_character,
    new_series_id,
    progress_of,
    slugify,
    validate_series,
    waiting_for,
)
from app.services.series_store import SeriesStore

logger = logging.getLogger(__name__)

_MODES = ("text", "ref", "chain")
_SCENE_KEYS = ("prompt", "mode", "beat", "characters", "duration_seconds", "seed")
_RESET_FIELDS = dict(
    job_id=None, attempts=0, progress=0, error=None, video_path=None,
    thumbnail_path=None, last_frame_path=None, started_at=None, finished_at=None,
)


class SeriesService:
    def __init__(self, store: SeriesStore, gateway: StudioGateway, outputs_dir: Path,
                 allowed_image_extensions: Sequence[str], max_image_bytes: int):
        self.store = store
        self.gateway = gateway
        self.outputs_dir = Path(outputs_dir)
        self.allowed_image_extensions = tuple(e.lower() for e in allowed_image_extensions)
        self.max_image_bytes = max_image_bytes

    # ---------- ภายใน ----------
    @staticmethod
    def _check(series: Series) -> None:
        errors = validate_series(series)
        if errors:
            raise SeriesError("; ".join(errors))

    def _commit(self, series: Series, event: str) -> None:
        """ตรวจทั้งก้อน แล้วค่อยแทนที่ของเดิมใน store (ไม่ผ่าน = ของเดิมไม่เปลี่ยน)"""
        self._check(series)
        self.store.add(series)
        self.store.save(series, event)

    def _cancel(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            try:
                self.gateway.cancel_job(job_id)
            except Exception:  # noqa: BLE001 — สถานะถูกบันทึกแล้ว ยกเลิกไม่สำเร็จไม่ควรทำให้การแก้ล้ม
                logger.warning("ยกเลิกงาน %s ไม่สำเร็จ", job_id, exc_info=True)

    @staticmethod
    def _reopen(series: Series) -> None:
        """กติกาสถานะซีรีส์เมื่อมีฉาก/ตอนที่ต้องทำใหม่"""
        if series.status == "CANCELLED":
            raise SeriesError("ซีรีส์ถูกยกเลิกแล้ว แก้ไขไม่ได้")
        if series.status == "DONE":
            series.status = "RUNNING"

    def _resolve_image(self, raw: str) -> Path:
        path = Path(raw)
        if not path.is_absolute():
            path = self.outputs_dir / path
        if not path.is_file():
            raise SeriesError(f"ไม่พบไฟล์รูป: {raw}")
        if path.suffix.lower() not in self.allowed_image_extensions:
            raise SeriesError(
                f"ชนิดไฟล์รูปไม่รองรับ: {raw} (ใช้ได้: {list(self.allowed_image_extensions)})"
            )
        if path.stat().st_size > self.max_image_bytes:
            raise SeriesError(f"ไฟล์รูปใหญ่เกินกำหนด ({self.max_image_bytes} ไบต์): {raw}")
        return path

    # ---------- สร้างซีรีส์ ----------
    def create_series(self, title: str, logline: str = "", style_notes: str = "",
                      aspect_ratio: str = DEFAULT_ASPECT_RATIO, megapixels: float = DEFAULT_MEGAPIXELS,
                      low_vram: bool = False, run_mode: str = "autopilot") -> Series:
        if not title.strip():
            raise SeriesError("ต้องระบุชื่อซีรีส์")
        if run_mode not in ("autopilot", "review"):
            raise SeriesError(f"run_mode '{run_mode}' ไม่รองรับ (ใช้ได้: autopilot, review)")
        with self.store.lock:
            now = time.time()
            series = Series(
                id=new_series_id(title), title=title, logline=logline, style_notes=style_notes,
                aspect_ratio=aspect_ratio, megapixels=megapixels, low_vram=low_vram,
                run_mode=run_mode, max_attempts=DEFAULT_MAX_ATTEMPTS, created_at=now, updated_at=now,
            )
            self._commit(series, "created")
            return series

    # ---------- ตัวละคร ----------
    def set_character(self, series_id: str, name: str, description: str = "",
                      image_paths: list[str] | None = None, casting_prompt: str | None = None) -> Character:
        if not name.strip():
            raise SeriesError("ต้องระบุชื่อตัวละคร")
        with self.store.lock:
            series = self.store.get(series_id).model_copy(deep=True)
            sources = [self._resolve_image(p) for p in (image_paths or [])]

            character = find_character(series, name)
            if character is None:
                character = Character(name=name)
                series.characters.append(character)
            position = series.characters.index(character) + 1
            stem = slugify(name) or f"char{position}"
            copies = [
                (src, f"series/{series_id}/refs/{stem}_{n}{src.suffix.lower()}")
                for n, src in enumerate(sources, start=1)
            ]

            old_casting_job = character.casting_job_id
            character.description = description
            character.casting_prompt = casting_prompt
            character.reference_images = [RefImage(path=rel) for _, rel in copies]
            character.casting_job_id = None
            character.casting_attempts = 0

            self._check(series)
            # อ่านไบต์ต้นทางทั้งหมดก่อนเขียน กันไฟล์ที่ส่งกลับมาจาก refs เดิมถูกเขียนทับก่อนถูกอ่าน
            payloads = [(src, self.outputs_dir / rel, src.read_bytes()) for src, rel in copies]
            for src, dest, data in payloads:
                if src.resolve() == dest.resolve():
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            self.store.add(series)
            self.store.save(series, f"character:{name}")
            if old_casting_job:
                self._cancel([old_casting_job])
            return character

    # ---------- ตอน ----------
    def write_episode(self, series_id: str, title: str, scenes: list[dict], synopsis: str = "",
                      caption: str = "", hashtags: list[str] | None = None,
                      episode_number: int | None = None) -> Episode:
        with self.store.lock:
            series = self.store.get(series_id).model_copy(deep=True)
            try:
                built = [
                    Scene(index=i, **{k: v for k, v in d.items() if k in _SCENE_KEYS})
                    for i, d in enumerate(scenes, start=1)
                ]
            except ValidationError as exc:
                first = exc.errors()[0]
                raise SeriesError(f"ข้อมูลฉากไม่ถูกต้อง: {first['loc']} {first['msg']}") from exc

            number = episode_number if episode_number is not None else len(series.episodes) + 1
            episode = Episode(
                number=number, title=title, synopsis=synopsis, caption=caption,
                hashtags=list(hashtags or []), scenes=built,
            )
            if episode_number is None:
                series.episodes.append(episode)
            else:
                pos = next((i for i, e in enumerate(series.episodes) if e.number == number), None)
                if pos is None:
                    raise SeriesError(f"ไม่พบตอนที่ {number}")
                if any(s.status != "PENDING" for s in series.episodes[pos].scenes):
                    raise SeriesError(f"ตอนที่ {number} เริ่มสร้างแล้ว เขียนทับไม่ได้")
                series.episodes[pos] = episode
            self._reopen(series)
            self._commit(series, f"episode:{number}")
            return episode

    def update_scene(self, series_id: str, episode_number: int, scene_index: int, *,
                     prompt: str | None = None, beat: str | None = None, mode: str | None = None,
                     characters: list[str] | None = None, duration_seconds: int | None = None,
                     seed: int | None = None, regenerate: bool = False) -> list[tuple[int, int]]:
        with self.store.lock:
            series = self.store.get(series_id).model_copy(deep=True)
            episode = next((e for e in series.episodes if e.number == episode_number), None)
            if episode is None:
                raise SeriesError(f"ไม่พบตอนที่ {episode_number}")
            scene = next((s for s in episode.scenes if s.index == scene_index), None)
            if scene is None:
                raise SeriesError(f"ไม่พบฉากที่ {scene_index} ในตอนที่ {episode_number}")
            if mode is not None and mode not in _MODES:
                raise SeriesError(f"mode '{mode}' ไม่รองรับ (ใช้ได้: {list(_MODES)})")

            must_reset = regenerate or scene.status in ("QUEUED", "RUNNING")
            edits = dict(prompt=prompt, beat=beat, mode=mode, characters=characters,
                         duration_seconds=duration_seconds, seed=seed)
            for field, value in edits.items():
                if value is not None:
                    setattr(scene, field, list(value) if field == "characters" else value)

            reset: list[tuple[int, int]] = []
            cancel_jobs: list[str] = []
            if must_reset:
                self._reopen(series)
                flat = [(e, s) for e in series.episodes for s in e.scenes]
                start = next(i for i, (_, s) in enumerate(flat) if s is scene)
                touched: list[Episode] = []
                for i in range(start, len(flat)):
                    ep, sc = flat[i]
                    if i > start and sc.mode != "chain":
                        break
                    if sc.job_id and sc.status in ("QUEUED", "RUNNING"):
                        cancel_jobs.append(sc.job_id)
                    sc.status = "PENDING"
                    for key, value in _RESET_FIELDS.items():
                        setattr(sc, key, value)
                    reset.append((ep.number, sc.index))
                    if ep not in touched:
                        touched.append(ep)
                for ep in touched:
                    ep.status = "PENDING"
                    ep.final_video_path = None
                    ep.thumbnail_path = None
                    ep.duration = None

            self._commit(series, f"scene:{episode_number}.{scene_index}")
            self._cancel(cancel_jobs)
            return reset

    # ---------- ควบคุม ----------
    def control(self, series_id: str, action: str) -> Series:
        with self.store.lock:
            series = self.store.get(series_id).model_copy(deep=True)
            if series.status == "CANCELLED":
                raise SeriesError("ซีรีส์ถูกยกเลิกแล้ว สั่งการไม่ได้")
            cancel_jobs: list[str] = []

            if action == "start":
                if series.status != "DRAFT":
                    raise SeriesError("เริ่มได้เฉพาะซีรีส์ที่เป็น DRAFT")
                if not series.episodes:
                    raise SeriesError("ต้องมีอย่างน้อย 1 ตอนก่อนเริ่ม")
                series.status = "RUNNING"
            elif action == "pause":
                if series.status != "RUNNING":
                    raise SeriesError("พักได้เฉพาะซีรีส์ที่กำลังรัน")
                series.status = "PAUSED"
                series.pause_reason = "user"
                series.pause_message = None
            elif action == "resume":
                if series.status != "PAUSED":
                    raise SeriesError("เล่นต่อได้เฉพาะซีรีส์ที่พักอยู่")
                if series.pause_reason == "error":
                    for episode in series.episodes:
                        for scene in episode.scenes:
                            if scene.status == "FAILED":
                                scene.status = "PENDING"
                                scene.attempts = 0
                                scene.error = None
                    for character in series.characters:
                        character.casting_attempts = 0
                series.status = "RUNNING"
                series.pause_reason = None
                series.pause_message = None
            elif action == "finish":
                series.story_complete = True
            elif action == "cancel":
                cancel_jobs = [
                    s.job_id for e in series.episodes for s in e.scenes
                    if s.job_id and s.status in ("QUEUED", "RUNNING")
                ] + [c.casting_job_id for c in series.characters if c.casting_job_id]
                series.status = "CANCELLED"
            else:
                raise SeriesError(
                    f"action '{action}' ไม่รองรับ (ใช้ได้: start, pause, resume, finish, cancel)"
                )

            self._commit(series, f"control:{action}")
            self._cancel(cancel_jobs)
            return series

    # ---------- อ่าน ----------
    def detail(self, series_id: str) -> dict:
        with self.store.lock:
            series = self.store.get(series_id)
            data = series.model_dump()
            data["progress"] = progress_of(series)
            data["waiting_for"] = waiting_for(series)
            return data

    def overview(self) -> list[dict]:
        with self.store.lock:
            return [
                {
                    "id": s.id, "title": s.title, "status": s.status,
                    "pause_reason": s.pause_reason, "waiting_for": waiting_for(s),
                    "episodes_done": sum(1 for e in s.episodes if e.status == "DONE"),
                    "episodes_total": len(s.episodes),
                    "progress": progress_of(s),
                }
                for s in self.store.list()
            ]
