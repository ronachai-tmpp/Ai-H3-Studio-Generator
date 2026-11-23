"""Series Runner: เดินซีรีส์ที่ RUNNING ทีละฉากผ่านคิวงาน แล้วรวมแต่ละตอนเป็นวิดีโอเดียว

`tick()` คือหนึ่งรอบของ state machine (เรียกจาก thread ใน Task 5 หรือจาก test ตรง ๆ)
ไม่แตะระบบไฟล์จริงหรือ config — ทุกอย่างผ่าน StudioGateway
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable

from app.services.series_export import write_manifest
from app.services.series_gateway import StudioGateway
from app.services.series_models import Episode, Scene, Series, find_character, job_type_for
from app.services.series_service import reset_scene
from app.services.series_store import SeriesStore


class SeriesRunner:
    def __init__(self, store: SeriesStore, gateway: StudioGateway,
                 tick_seconds: float = 1.0, clock: Callable[[], float] = time.time):
        self.store = store
        self.gateway = gateway
        self.tick_seconds = tick_seconds
        self.clock = clock
        self._submitted: set[str] = set()  # งานที่ runner นี้ส่งเอง (แยก "ผู้ใช้ลบงาน" ออกจาก "แอปรีสตาร์ต")

    def tick(self) -> None:
        """หนึ่งรอบ ครอบคลุมทุกซีรีส์ที่ RUNNING (ซีรีส์ละหนึ่งการเปลี่ยนแปลง)"""
        with self.store.lock:
            ids = [s.id for s in self.store.list() if s.status == "RUNNING"]
        for series_id in ids:
            self._advance(series_id)

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

        status = job["status"]
        if status == "RUNNING":
            scene.status = "RUNNING"
            scene.progress = job.get("progress") or 0  # แค่สะท้อนในหน่วยความจำ ไม่บันทึก
        elif status == "DONE":
            video = job.get("video_path") or self.gateway.find_output_video(scene.job_id)
            scene.video_path = video
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
