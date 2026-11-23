"""manifest, การ export ไฟล์ตอน และภาพสำหรับรีวิว (ใช้โดย runner และเครื่องมือ MCP)"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from app.services.series_gateway import StudioGateway
from app.services.series_models import Series, SeriesError, find_character
from app.services.series_store import SeriesStore

MANIFEST_FILE = "manifest.json"
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


def build_manifest(series: Series) -> dict:
    """สรุปซีรีส์เป็น dict (เฉพาะตอนที่ DONE; video = final_video_path)"""
    return {
        "id": series.id,
        "title": series.title,
        "logline": series.logline,
        "aspect_ratio": series.aspect_ratio,
        "story_complete": series.story_complete,
        "episodes": [
            {
                "number": e.number,
                "title": e.title,
                "synopsis": e.synopsis,
                "caption": e.caption,
                "hashtags": list(e.hashtags),
                "video": e.final_video_path,
                "thumbnail": e.thumbnail_path,
                "duration": e.duration,
            }
            for e in series.episodes
            if e.status == "DONE"
        ],
    }


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_manifest(store: SeriesStore, series: Series) -> Path:
    """เขียน series/<id>/manifest.json"""
    path = store.series_dir(series.id) / MANIFEST_FILE
    _write_json(path, build_manifest(series))
    return path


def safe_filename(text: str) -> str:
    """ทำชื่อไฟล์ให้ปลอดภัยบน Windows (คงภาษาไทยไว้) อาจคืนสตริงว่าง"""
    cleaned = _ILLEGAL_CHARS.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.rstrip(". ")


def export_series(store: SeriesStore, outputs_dir: Path, series_id: str) -> dict:
    """คัดลอกตอนที่ DONE ไป series/<id>/export พร้อมชื่อไฟล์อ่านง่ายและ manifest.json"""
    series = store.get(series_id)
    manifest = build_manifest(series)
    if not manifest["episodes"]:
        raise SeriesError("ยังไม่มีตอนที่เสร็จให้ export")

    outputs_dir = Path(outputs_dir)
    export_dir = outputs_dir / "series" / series.id / "export"
    export_dir.mkdir(parents=True, exist_ok=True)

    files: list[str] = []
    by_number = {e.number: e for e in series.episodes}
    for entry in manifest["episodes"]:
        episode = by_number[entry["number"]]
        stem = f"EP{episode.number:02d}"
        title = safe_filename(episode.title)
        video_name = f"{stem} - {title}.mp4" if title else f"{stem}.mp4"
        source = outputs_dir / (episode.final_video_path or "")
        if not episode.final_video_path or not source.is_file():
            raise SeriesError(f"ไม่พบไฟล์วิดีโอของตอนที่ {episode.number}")
        shutil.copy2(source, export_dir / video_name)
        files.append(video_name)
        entry["video"] = video_name

        thumb_source = outputs_dir / (episode.thumbnail_path or "")
        if episode.thumbnail_path and thumb_source.is_file():
            thumb_name = f"{stem}.jpg"
            shutil.copy2(thumb_source, export_dir / thumb_name)
            files.append(thumb_name)
            entry["thumbnail"] = thumb_name
        else:
            entry["thumbnail"] = None

    _write_json(export_dir / MANIFEST_FILE, manifest)
    files.append(MANIFEST_FILE)
    return {"dir": f"series/{series.id}/export", "files": files}


def review_images(store: SeriesStore, gateway: StudioGateway, series_id: str, *,
                  episode: int | None = None, scene: int | None = None,
                  character: str | None = None, frames: int = 4) -> tuple[str, list[str]]:
    """คืน (ข้อความ, path รูปแบบ relative กับ outputs) สำหรับให้ Claude ดูรีวิว"""
    series = store.get(series_id)
    if (episode is None) == (character is None):
        raise SeriesError("ต้องระบุ episode หรือ character อย่างใดอย่างหนึ่งเท่านั้น")

    if character is not None:
        char = find_character(series, character)
        if char is None:
            raise SeriesError(f"ไม่พบตัวละคร '{character}'")
        images = [r.path for r in char.reference_images]
        if not images:
            raise SeriesError(f"ตัวละคร '{character}' ยังไม่มีรูปอ้างอิง")
        return f"ตัวละคร {char.name}: {char.description}", images

    ep = next((e for e in series.episodes if e.number == episode), None)
    if ep is None:
        raise SeriesError(f"ไม่พบตอนที่ {episode}")

    if scene is not None:
        sc = next((s for s in ep.scenes if s.index == scene), None)
        if sc is None:
            raise SeriesError(f"ไม่พบฉากที่ {scene} ในตอนที่ {episode}")
        if sc.status != "DONE" or not sc.video_path:
            raise SeriesError(f"ฉากที่ {scene} ของตอนที่ {episode} ยังไม่เสร็จ")
        count = max(1, min(8, frames))
        # ใส่ job_id ในชื่อโฟลเดอร์: สร้างฉากใหม่แล้วจะไม่ปนกับเฟรมของคลิปเก่า (ไฟล์เก่าไม่ถูกลบ)
        out_dir = f"series/{series.id}/review/ep{ep.number:02d}_s{sc.index:02d}"
        if sc.job_id:
            out_dir += f"_{sc.job_id}"
        images = gateway.sample_frames(sc.video_path, out_dir, count, max_edge=512)
        text = (f"ตอนที่ {ep.number} ฉากที่ {sc.index} (mode {sc.mode}, "
                f"{sc.duration_seconds} วินาที)\nprompt: {sc.prompt}")
        return text, images

    done = [s for s in ep.scenes if s.status == "DONE" and s.last_frame_path]
    if not done:
        raise SeriesError(f"ตอนที่ {episode} ยังไม่มีฉากที่เสร็จ")
    lines = [f"ตอนที่ {ep.number}: เฟรมสุดท้ายของแต่ละฉาก"]
    lines += [f"ฉากที่ {s.index}: {s.beat}" for s in done]
    return "\n".join(lines), [s.last_frame_path for s in done]
