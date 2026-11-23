"""Series Runner: เดินซีรีส์ที่ RUNNING ทีละฉากผ่านคิวงาน แล้วรวมแต่ละตอนเป็นวิดีโอเดียว

`tick()` คือหนึ่งรอบของ state machine (เรียกจาก thread ใน Task 5 หรือจาก test ตรง ๆ)
ไม่แตะระบบไฟล์จริงหรือ config — ทุกอย่างผ่าน StudioGateway
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
import traceback
from collections.abc import Callable

from app.services.series_export import write_manifest
from app.services.series_gateway import StudioGateway
from app.services.series_models import (
    CASTING_DURATION_SECONDS, Character, Episode, RefImage, Scene, Series,
    find_character, job_type_for, needs_casting,
)
from app.services.series_service import character_stem, reset_scene
from app.services.series_store import SeriesStore

logger = logging.getLogger(__name__)


class SeriesRunner:
    def __init__(self, store: SeriesStore, gateway: StudioGateway,
                 tick_seconds: float = 1.0, clock: Callable[[], float] = time.time):
        self.store = store
        self.gateway = gateway
        self.tick_seconds = tick_seconds
        self.clock = clock
        self._submitted: set[str] = set()  # งานที่ runner นี้ส่งเอง (แยก "ผู้ใช้ลบงาน" ออกจาก "แอปรีสตาร์ต")
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ---------- thread ----------
    def start(self) -> None:
        """เริ่ม thread พื้นหลังที่เรียก tick() ทุก tick_seconds (เรียกซ้ำได้)"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="h3-series-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """สั่งหยุดแล้วรอจน loop จบจริง (รวมรอบ tick ที่กำลังทำอยู่)"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 — tick พังต้องไม่ฆ่า thread
                traceback.print_exc()
            self._stop.wait(self.tick_seconds)

    def tick(self) -> None:
        """หนึ่งรอบ ครอบคลุมทุกซีรีส์ที่ RUNNING (ซีรีส์ละหนึ่งการเปลี่ยนแปลง)"""
        with self.store.lock:
            ids = [s.id for s in self.store.list() if s.status == "RUNNING"]
        for series_id in ids:
            try:
                self._advance(series_id)
            except Exception as exc:  # noqa: BLE001 — ซีรีส์หนึ่งพังต้องไม่ลากซีรีส์อื่นหยุดตาม
                logger.exception("Series %s: runner error", series_id)
                self._pause_on_error(series_id, exc)

    def _pause_on_error(self, series_id: str, exc: Exception) -> None:
        with self.store.lock:
            series = self.store.get(series_id)
            if series.status == "RUNNING":
                self._pause(series, "error", f"ข้อผิดพลาดภายใน: {exc}", f"series error: {exc}")

    # ---------- ตัวช่วย ----------
    @staticmethod
    def _label(episode: Episode, scene: Scene) -> str:
        return f"EP{episode.number:02d} scene {scene.index}"

    def _pause(self, series: Series, reason: str, message: str | None, event: str) -> None:
        series.status = "PAUSED"
        series.pause_reason = reason
        series.pause_message = message
        self.store.save(series, event)

    # ---------- หนึ่งซีรีส์ ----------
    def _advance(self, series_id: str) -> None:
        merge = None
        with self.store.lock:
            series = self.store.get(series_id)
            if series.status != "RUNNING":
                return
            if self._advance_casting(series):
                return
            episode = next((e for e in series.episodes if e.status != "DONE"), None)
            if episode is None:
                if series.story_complete:
                    series.status = "DONE"
                    self.store.save(series, "series DONE")
                return
            scene = next((s for s in episode.scenes if s.status != "DONE"), None)
            if scene is None:
                merge = self._prepare_merge(series, episode)
            elif scene.job_id is None:
                self._submit(series, episode, scene)
            else:
                self._poll(series, episode, scene)
        if merge is not None:
            self._merge(series_id, *merge)

    # ---------- คัดตัวละคร (auto-casting) ----------
    def _advance_casting(self, series: Series) -> bool:
        """คืน True ถ้ามีการคัดตัวละครค้างอยู่ในซีรีส์นี้ (รอบนี้จบแค่นี้)"""
        character = next((c for c in series.characters if c.casting_job_id), None)
        if character is not None:
            self._poll_casting(series, character)
            return True
        character = next((c for c in series.characters if needs_casting(c)), None)
        if character is None:
            return False
        character.casting_job_id = self.gateway.submit_job(
            prompt=character.casting_prompt, job_type=job_type_for("text", series.low_vram),
            megapixels=series.megapixels, aspect_ratio=series.aspect_ratio,
            duration_seconds=CASTING_DURATION_SECONDS, seed=-1,
        )
        self._submitted.add(character.casting_job_id)
        self.store.save(series, f"casting {character.name} QUEUED")
        return True

    def _poll_casting(self, series: Series, character: Character) -> None:
        job_id = character.casting_job_id
        job = self.gateway.get_job(job_id)
        if job is None:
            video = self.gateway.find_output_video(job_id)
            if video is not None:
                job = dict(status="DONE", video_path=video)
            elif job_id in self._submitted:
                character.casting_job_id = None
                self._pause(series, "user", None, f"casting {character.name} job removed")
                return
            else:  # แอปรีสตาร์ตแล้วงานหายจากคิว: ส่งใหม่ ไม่นับเป็นความพยายาม
                character.casting_job_id = None
                self.store.save(series, f"casting {character.name} job lost, resubmit")
                return

        status = job["status"]
        error = job.get("error")
        if status == "DONE":
            video = job.get("video_path") or self.gateway.find_output_video(job_id)
            if not video:  # งานบอกเสร็จแต่ไม่มีไฟล์วิดีโอ: นับเหมือนล้มเหลว
                status, error = "FAILED", "งานเสร็จแล้วแต่ไม่มีไฟล์วิดีโอ (job finished without a video file)"
            else:
                dest = f"series/{series.id}/refs/{character_stem(series, character)}_cast.jpg"
                if self.gateway.extract_frame(video, dest, "last", 3):
                    self._finish_casting(series, character, dest)
                    return
                status, error = "FAILED", "ดึงเฟรมจากวิดีโอคัดตัวละครไม่ได้ (extract frame failed)"

        if status == "FAILED":
            character.casting_attempts += 1
            character.casting_job_id = None
            if character.casting_attempts < series.max_attempts:
                self.store.save(series, f"casting {character.name} retry {character.casting_attempts}")
            else:
                self._pause(series, "error", f"คัดตัวละคร {character.name} ล้มเหลว: {error}",
                            f"casting {character.name} FAILED: {error}")
        elif status == "CANCELLED":
            character.casting_job_id = None
            self._pause(series, "user", None, f"casting {character.name} cancelled")

    def _finish_casting(self, series: Series, character: Character, ref_path: str) -> None:
        character.reference_images = [RefImage(path=ref_path)]
        character.casting_job_id = None
        event = f"character {character.name} cast"
        if any(needs_casting(c) for c in series.characters):
            self.store.save(series, event)
            return
        names = [c.name for c in series.characters
                 if c.reference_images and c.reference_images[0].path.endswith("_cast.jpg")]
        self._pause(series, "casting", f"คัดตัวละครเสร็จแล้ว กรุณาตรวจรูป: {', '.join(names)}", event)

    # ---------- ส่งงาน ----------
    def _submit(self, series: Series, episode: Episode, scene: Scene) -> None:
        reference_names: list[str] | None = None
        first_frame_name: str | None = None
        if scene.mode == "ref":
            reference_names = self._reference_names(series, scene)
        elif scene.mode == "chain":
            first_frame_name = self._first_frame_name(series, episode, scene)
            if first_frame_name is None:
                return  # หยุดซีรีส์ไปแล้ว (ดึงเฟรมจากฉากก่อนหน้าไม่ได้)

        episode.status = "RUNNING"
        scene.job_id = self.gateway.submit_job(
            prompt=scene.prompt, job_type=job_type_for(scene.mode, series.low_vram),
            megapixels=series.megapixels, aspect_ratio=series.aspect_ratio,
            duration_seconds=scene.duration_seconds, seed=scene.seed,
            reference_names=reference_names, first_frame_name=first_frame_name,
        )
        self._submitted.add(scene.job_id)
        scene.status = "QUEUED"
        scene.started_at = self.clock()
        self.store.save(series, f"{self._label(episode, scene)} QUEUED")

    def _reference_names(self, series: Series, scene: Scene) -> list[str]:
        base_url = self.gateway.comfy_base_url()
        names: list[str] = []
        for char_name in scene.characters:
            character = find_character(series, char_name)
            for image in character.reference_images if character else []:
                reusable = (
                    image.comfy_name is not None
                    and image.comfy_base_url == base_url
                    and self.gateway.comfy_input_exists(image.comfy_name) is not False
                )
                if not reusable:
                    image.comfy_name = self.gateway.push_image(image.path)
                    image.comfy_base_url = base_url
                names.append(image.comfy_name)
        return names

    def _first_frame_name(self, series: Series, episode: Episode, scene: Scene) -> str | None:
        flat = [(e, s) for e in series.episodes for s in e.scenes]
        position = next(i for i, (_, s) in enumerate(flat) if s is scene)
        previous = flat[position - 1][1]
        frame = previous.last_frame_path
        if not frame or not self.gateway.output_exists(frame):
            frame = f"frames/{previous.job_id}_last.jpg"
            if not self.gateway.extract_frame(previous.video_path, frame, "last", 0):
                self._pause(series, "error",
                            f"ดึงเฟรมสุดท้ายของ {self._label(*flat[position - 1])} ไม่ได้",
                            f"{self._label(episode, scene)} FAILED: extract frame")
                return None
            previous.last_frame_path = frame
        return self.gateway.push_image(frame)

    # ---------- ตามผลงาน ----------
    def _poll(self, series: Series, episode: Episode, scene: Scene) -> None:
        label = self._label(episode, scene)
        job = self.gateway.get_job(scene.job_id)
        if job is None:
            video = self.gateway.find_output_video(scene.job_id)
            if video is not None:
                thumb = f"thumbnails/{scene.job_id}.jpg"
                job = dict(status="DONE", video_path=video,
                           thumbnail_path=thumb if self.gateway.output_exists(thumb) else None)
            elif scene.job_id in self._submitted:
                scene.job_id, scene.status = None, "PENDING"
                self._pause(series, "user", None, f"{label} job removed")
                return
            else:  # แอปรีสตาร์ตแล้วงานหายจากคิว: ส่งใหม่ ไม่นับเป็นความพยายาม
                scene.job_id, scene.status = None, "PENDING"
                self.store.save(series, f"{label} job lost, resubmit")
                return

        if job["status"] == "DONE" and not (
            job.get("video_path") or self.gateway.find_output_video(scene.job_id)
        ):  # งานบอกเสร็จแต่ไม่มีไฟล์วิดีโอ: นับเหมือนล้มเหลว (กันวนใช้ GPU ไม่จบ)
            job = dict(status="FAILED", error="งานเสร็จแล้วแต่ไม่มีไฟล์วิดีโอ (job finished without a video file)")

        status = job["status"]
        if status == "RUNNING":
            scene.status = "RUNNING"
            scene.progress = job.get("progress") or 0  # แค่สะท้อนในหน่วยความจำ ไม่บันทึก
        elif status == "DONE":
            scene.video_path = job.get("video_path") or self.gateway.find_output_video(scene.job_id)
            scene.thumbnail_path = job.get("thumbnail_path")
            scene.last_frame_path = f"frames/{scene.job_id}_last.jpg"
            scene.progress = 100
            scene.finished_at = self.clock()
            scene.status = "DONE"
            self.store.save(series, f"{label} DONE")
        elif status == "FAILED":
            scene.attempts += 1
            scene.error = job.get("error")
            scene.progress = 0
            scene.job_id = None
            if scene.attempts < series.max_attempts:
                scene.status = "PENDING"
                self.store.save(series, f"{label} retry {scene.attempts}")
            else:
                scene.status = "FAILED"
                self._pause(series, "error",
                            f"ตอนที่ {episode.number} ฉากที่ {scene.index} ล้มเหลว: {scene.error}",
                            f"{label} FAILED: {scene.error}")
        elif status == "CANCELLED":
            scene.job_id, scene.status, scene.progress = None, "PENDING", 0
            self._pause(series, "user", None, f"{label} cancelled")

    # ---------- รวมตอน ----------
    def _prepare_merge(self, series: Series, episode: Episode):
        """ทุกฉาก DONE: ไฟล์หาย → รีเซ็ตฉากนั้น; ฉากเดียว → จบตอนเลย; หลายฉาก → คืนงานให้ concat นอก lock"""
        for scene in episode.scenes:
            if not scene.video_path or not self.gateway.output_exists(scene.video_path):
                reset_scene(series, self.gateway, episode.number, scene.index)
                self.store.save(series, f"{self._label(episode, scene)} file missing, regenerate")
                return None
        if len(episode.scenes) == 1:
            scene = episode.scenes[0]
            job = self.gateway.get_job(scene.job_id)
            self._finish_episode(series, episode, scene.video_path, scene.thumbnail_path,
                                 job.get("duration") if job else None)
            return None
        paths = [s.video_path for s in episode.scenes]
        return episode.number, paths

    def _merge(self, series_id: str, episode_number: int, paths: list[str]) -> None:
        stem = f"series_{series_id}_ep{episode_number:02d}_{secrets.token_hex(3)}"
        final, thumb = f"videos/{stem}.mp4", f"thumbnails/{stem}.jpg"
        result = self.gateway.concat(paths, final)
        info = self.gateway.make_thumbnail(final, thumb) if result.get("ok") else {}

        with self.store.lock:  # concat ใช้เวลานาน: ตรวจซ้ำว่าระหว่างนั้นไม่มีใครสั่งทำฉากใหม่
            series = self.store.get(series_id)
            episode = next((e for e in series.episodes if e.number == episode_number), None)
            if (
                series.status != "RUNNING" or episode is None or episode.status == "DONE"
                or [s.video_path for s in episode.scenes] != paths
                or any(s.status != "DONE" for s in episode.scenes)
            ):
                return
            if not result.get("ok"):
                self._pause(series, "error",
                            f"รวมวิดีโอตอนที่ {episode_number} ไม่สำเร็จ: {result.get('error')}",
                            f"EP{episode_number:02d} merge FAILED: {result.get('error')}")
                return
            self._finish_episode(series, episode, final,
                                 thumb if info.get("thumbnail_created") else None, info.get("duration"))

    def _finish_episode(self, series: Series, episode: Episode, video: str, thumbnail: str | None,
                        duration: float | None) -> None:
        episode.final_video_path = video
        episode.thumbnail_path = thumbnail
        episode.duration = duration
        episode.status = "DONE"
        write_manifest(self.store, series)
        self.store.save(series, f"EP{episode.number:02d} DONE")
        if series.run_mode == "review":
            self._pause(series, "review", None, f"EP{episode.number:02d} review")
