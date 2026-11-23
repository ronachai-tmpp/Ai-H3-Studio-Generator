"""Series Runner: เดินซีรีส์ที่ RUNNING ทีละฉากผ่านคิวงาน แล้วรวมแต่ละตอนเป็นวิดีโอเดียว

`tick()` คือหนึ่งรอบของ state machine (เรียกจาก thread ใน Task 5 หรือจาก test ตรง ๆ)
ไม่แตะระบบไฟล์จริงหรือ config — ทุกอย่างผ่าน StudioGateway
"""

from __future__ import annotations

import functools
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
    clip_error, find_character, job_type_for, needs_casting,
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
        series.pause_message = clip_error(message)
        self.store.save(series, clip_error(event))

    # ---------- หนึ่งซีรีส์ ----------
    def _advance(self, series_id: str) -> None:
        """ใต้ lock: ตัดสินใจขั้นถัดไป ขั้นที่ไม่ต้องรอ I/O ทำเสร็จในนี้เลย

        ขั้นที่ต้องคุยกับ ComfyUI/ffmpeg (อัปโหลดรูป ดึงเฟรม รวมวิดีโอ) คืนเป็นงานให้ทำนอก lock
        งานนั้นกลับเข้า lock เอง ตรวจซ้ำว่ายังต้องทำขั้นนี้อยู่ แล้วค่อยบันทึกผล
        """
        work: Callable[[], None] | None = None
        with self.store.lock:
            series = self.store.get(series_id)
            if series.status != "RUNNING":
                return
            casting = next((c for c in series.characters if c.casting_job_id), None)
            uncast = next((c for c in series.characters if needs_casting(c)), None)
            episode, scene = self._current(series)
            if casting is not None:
                work = self._poll_casting(series, casting)
            elif uncast is not None:
                self._submit_casting(series, uncast)
            elif episode is None:
                if series.story_complete:
                    series.status = "DONE"
                    write_manifest(self.store, series)
                    self.store.save(series, "series DONE")
            elif scene is None:
                work = self._prepare_merge(series, episode)
            elif scene.job_id is None:
                work = self._prepare_submit(series, episode, scene)
            else:
                self._poll(series, episode, scene)
        if work is not None:
            work()

    @staticmethod
    def _current(series: Series) -> tuple[Episode | None, Scene | None]:
        """ตอนแรกที่ยังไม่ DONE กับฉากแรกในตอนนั้นที่ยังไม่ DONE"""
        episode = next((e for e in series.episodes if e.status != "DONE"), None)
        scene = next((s for s in episode.scenes if s.status != "DONE"), None) if episode else None
        return episode, scene

    # ---------- คัดตัวละคร (auto-casting) ----------
    def _submit_casting(self, series: Series, character: Character) -> None:
        character.casting_job_id = self.gateway.submit_job(
            prompt=character.casting_prompt, job_type=job_type_for("text", series.low_vram),
            megapixels=series.megapixels, aspect_ratio=series.aspect_ratio,
            duration_seconds=CASTING_DURATION_SECONDS, seed=-1,
        )
        self._submitted.add(character.casting_job_id)
        self.store.save(series, f"casting {character.name} QUEUED")

    def _poll_casting(self, series: Series, character: Character) -> Callable[[], None] | None:
        """ตามผลงานคัดตัวละคร; งานเสร็จ → คืนงานดึงเฟรมให้ทำนอก lock"""
        job_id = character.casting_job_id
        job = self.gateway.get_job(job_id)
        if job is None:
            video = self.gateway.find_output_video(job_id)
            if video is not None:
                job = dict(status="DONE", video_path=video)
            elif job_id in self._submitted:
                character.casting_job_id = None
                self._pause(series, "user", None, f"casting {character.name} job removed")
                return None
            else:  # แอปรีสตาร์ตแล้วงานหายจากคิว: ส่งใหม่ ไม่นับเป็นความพยายาม
                character.casting_job_id = None
                self.store.save(series, f"casting {character.name} job lost, resubmit")
                return None

        status = job["status"]
        if status == "DONE":
            video = job.get("video_path") or self.gateway.find_output_video(job_id)
            if not video:  # งานบอกเสร็จแต่ไม่มีไฟล์วิดีโอ: นับเหมือนล้มเหลว
                self._casting_failed(series, character,
                                     "งานเสร็จแล้วแต่ไม่มีไฟล์วิดีโอ (job finished without a video file)")
                return None
            dest = f"series/{series.id}/refs/{character_stem(series, character)}_cast.jpg"
            return functools.partial(self._extract_cast, series.id, self.store.revision(series.id),
                                     character.name, job_id, video, dest)
        if status == "FAILED":
            self._casting_failed(series, character, job.get("error"))
        elif status == "CANCELLED":
            character.casting_job_id = None
            self._pause(series, "user", None, f"casting {character.name} cancelled")
        return None

    def _extract_cast(self, series_id: str, revision: int, name: str, job_id: str, video: str,
                      dest: str) -> None:
        """นอก lock: ดึงเฟรมจากวิดีโอคัดตัวละคร แล้วกลับเข้า lock บันทึกผลถ้าตัวละครยังรอผลงานนี้อยู่"""
        # ffmpeg บางรุ่นดึงเฟรมย้อนหลังไม่ได้ (offset 3): ถอยไปใช้เฟรมสุดท้ายตรง ๆ
        ok = (self.gateway.extract_frame(video, dest, "last", 3)
              or self.gateway.extract_frame(video, dest, "last", 0))
        with self.store.lock:
            series = self.store.get(series_id)
            character = find_character(series, name)
            if (self.store.revision(series_id) != revision or series.status != "RUNNING"
                    or character is None or character.casting_job_id != job_id):
                return  # ระหว่างดึงเฟรมมีคนแก้ซีรีส์ (พัก/ยกเลิก/คัดตัวใหม่ ฯลฯ): ทิ้งผลนี้ รอบหน้าทำใหม่
            if ok:
                self._finish_casting(series, character, dest)
            else:
                self._casting_failed(series, character,
                                     "ดึงเฟรมจากวิดีโอคัดตัวละครไม่ได้ (extract frame failed)")

    def _casting_failed(self, series: Series, character: Character, error: str | None) -> None:
        character.casting_attempts += 1
        character.casting_job_id = None
        if character.casting_attempts < series.max_attempts:
            self.store.save(series, f"casting {character.name} retry {character.casting_attempts}")
        else:
            self._pause(series, "error", f"คัดตัวละคร {character.name} ล้มเหลว: {error}",
                        f"casting {character.name} FAILED: {error}")

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
    def _prepare_submit(self, series: Series, episode: Episode, scene: Scene) -> Callable[[], None] | None:
        """ฉาก text ส่งได้ทันที; ref/chain ต้องอัปโหลดรูปหรือดึงเฟรมก่อน จึงคืนงานให้ทำนอก lock

        ข้อมูลที่งานนอก lock ใช้ถูกคัดลอกออกมาเป็นค่าธรรมดา (path, ชื่อใน ComfyUI, base URL)
        """
        key = self._submit_key(series, episode, scene)
        if scene.mode == "ref":
            images = [(i.path, i.comfy_name, i.comfy_base_url) for i in self._scene_images(series, scene)]
            return functools.partial(self._submit_ref, series.id, key, images, self.gateway.comfy_base_url())
        if scene.mode == "chain":
            previous_episode, previous = self._previous(series, scene)
            frame = previous.last_frame_path
            extract = not frame or not self.gateway.output_exists(frame)
            if extract:
                frame = f"frames/{previous.job_id}_last.jpg"
            return functools.partial(self._submit_chain, series.id, key, previous.video_path, frame,
                                     extract, self._label(previous_episode, previous))
        self._submit(series, episode, scene)
        return None

    def _submit_key(self, series: Series, episode: Episode, scene: Scene) -> tuple:
        """สิ่งที่การเตรียมส่งฉากขึ้นอยู่ด้วย — ถ้าเปลี่ยนระหว่างทำ I/O นอก lock ผลที่เตรียมไว้ใช้ไม่ได้

        รวม revision ของ store ด้วย: การแก้ใด ๆ ระหว่างนั้น (เช่นเปลี่ยนรูปตัวละครโดยใช้ path เดิม)
        ทำให้ทิ้งผลที่เตรียมไว้ แล้วรอบหน้าค่อยเตรียมใหม่จากข้อมูลล่าสุด
        """
        if scene.mode == "ref":
            inputs: tuple = tuple(i.path for i in self._scene_images(series, scene))
        elif scene.mode == "chain":
            _, previous = self._previous(series, scene)
            inputs = (previous.job_id, previous.video_path)
        else:
            inputs = ()
        return self.store.revision(series.id), episode.number, scene.index, scene.mode, inputs

    def _still_next(self, series_id: str, key: tuple) -> tuple[Series, Episode, Scene] | None:
        """ใต้ lock: คืน (series, episode, scene) ตัวจริงถ้าฉากที่เตรียมไว้ยังเป็นงานถัดไปแบบเดิม ไม่งั้น None"""
        series = self.store.get(series_id)
        if series.status != "RUNNING" or any(c.casting_job_id or needs_casting(c) for c in series.characters):
            return None
        episode, scene = self._current(series)
        if scene is None or scene.job_id is not None or self._submit_key(series, episode, scene) != key:
            return None
        return series, episode, scene

    def _submit_ref(self, series_id: str, key: tuple, images: list[tuple[str, str | None, str | None]],
                    base_url: str) -> None:
        """นอก lock: อัปโหลดรูปอ้างอิงที่ ComfyUI ยังไม่มี (โหมด RunPod = HTTP ช้า) แล้วกลับเข้า lock ส่งงาน"""
        names: list[str] = []
        pushed: dict[str, str] = {}
        for path, name, url in images:
            if path in pushed:
                name = pushed[path]
            elif name is None or url != base_url or self.gateway.comfy_input_exists(name) is False:
                name = pushed[path] = self.gateway.push_image(path)
            names.append(name)
        with self.store.lock:
            found = self._still_next(series_id, key)
            if found is None:
                return  # ระหว่างอัปโหลดมีคนพัก/แก้ฉาก: ทิ้งผลนี้ รอบหน้าค่อยเตรียมใหม่
            series, episode, scene = found
            for image, name in zip(self._scene_images(series, scene), names):
                image.comfy_name, image.comfy_base_url = name, base_url
            self._submit(series, episode, scene, reference_names=names)

    def _submit_chain(self, series_id: str, key: tuple, video: str | None, frame: str, extract: bool,
                      previous_label: str) -> None:
        """นอก lock: ดึงเฟรมสุดท้ายของฉากก่อนหน้า (ถ้ายังไม่มีไฟล์) แล้วอัปโหลดเป็นเฟรมแรก จากนั้นกลับเข้า lock ส่งงาน"""
        extracted = not extract or self.gateway.extract_frame(video, frame, "last", 0)
        name = self.gateway.push_image(frame) if extracted else None
        with self.store.lock:
            found = self._still_next(series_id, key)
            if found is None:
                return
            series, episode, scene = found
            if name is None:
                self._pause(series, "error", f"ดึงเฟรมสุดท้ายของ {previous_label} ไม่ได้",
                            f"{self._label(episode, scene)} FAILED: extract frame")
                return
            if extract:
                self._previous(series, scene)[1].last_frame_path = frame
            self._submit(series, episode, scene, first_frame_name=name)

    def _submit(self, series: Series, episode: Episode, scene: Scene,
                reference_names: list[str] | None = None, first_frame_name: str | None = None) -> None:
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

    @staticmethod
    def _scene_images(series: Series, scene: Scene) -> list[RefImage]:
        """รูปอ้างอิงทั้งหมดของตัวละครในฉาก ตามลำดับที่ส่งให้ ComfyUI"""
        images: list[RefImage] = []
        for name in scene.characters:
            character = find_character(series, name)
            images.extend(character.reference_images if character else [])
        return images

    @staticmethod
    def _previous(series: Series, scene: Scene) -> tuple[Episode, Scene]:
        """ฉากก่อนหน้าในลำดับทั้งเรื่อง (ข้ามตอนได้)"""
        flat = [(e, s) for e in series.episodes for s in e.scenes]
        position = next(i for i, (_, s) in enumerate(flat) if s is scene)
        return flat[position - 1]

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
            scene.error = None  # ความพยายามก่อนหน้าที่ล้มเหลวไม่เกี่ยวแล้ว
            scene.finished_at = self.clock()
            scene.status = "DONE"
            self.store.save(series, f"{label} DONE")
        elif status == "FAILED":
            scene.attempts += 1
            scene.error = clip_error(job.get("error"))
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
    def _prepare_merge(self, series: Series, episode: Episode) -> Callable[[], None] | None:
        """ทุกฉาก DONE: ไฟล์หาย → รีเซ็ตฉากนั้น; ฉากเดียว → จบตอนเลย; หลายฉาก → คืนงานให้ concat นอก lock"""
        for scene in episode.scenes:
            if not scene.video_path or not self.gateway.output_exists(scene.video_path):
                reset_scene(series, self.gateway, episode.number, scene.index)
                write_manifest(self.store, series)
                self.store.save(series, f"{self._label(episode, scene)} file missing, regenerate")
                return None
        if len(episode.scenes) == 1:
            scene = episode.scenes[0]
            job = self.gateway.get_job(scene.job_id)
            self._finish_episode(series, episode, scene.video_path, scene.thumbnail_path,
                                 job.get("duration") if job else None)
            return None
        paths = [s.video_path for s in episode.scenes]
        return functools.partial(self._merge, series.id, episode.number, paths)

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
