"""ช่องทางที่ Series Runner ใช้คุยกับส่วนอื่นของ Studio (คิวงาน, ComfyUI, ffmpeg)

แยกเป็น Protocol เพื่อให้ทดสอบด้วย FakeGateway ได้โดยไม่ต้องมี ComfyUI จริง
"""

from __future__ import annotations

from typing import Protocol


class StudioGateway(Protocol):
    def submit_job(self, *, prompt: str, job_type: str, megapixels: float, aspect_ratio: str,
                   duration_seconds: int, seed: int,
                   reference_names: list[str] | None = None,
                   first_frame_name: str | None = None) -> str: ...

    def get_job(self, job_id: str) -> dict | None: ...   # keys: status, progress, error, video_path, thumbnail_path, duration

    def cancel_job(self, job_id: str) -> None: ...

    def find_output_video(self, job_id: str) -> str | None: ...   # "videos/<job_id>.<ext>" ถ้ามีไฟล์

    def output_exists(self, rel_path: str) -> bool: ...

    def push_image(self, rel_path: str) -> str: ...      # → ชื่อไฟล์ใน ComfyUI input

    def comfy_base_url(self) -> str: ...

    def comfy_input_exists(self, name: str) -> bool | None: ...   # None = ตรวจไม่ได้ (remote)

    def extract_frame(self, video_rel: str, dest_rel: str, position: str = "last",
                      offset_from_end: int = 0) -> bool: ...

    def concat(self, video_rels: list[str], dest_rel: str) -> dict: ...        # {"ok": bool, "error": str | None}

    def make_thumbnail(self, video_rel: str, thumb_rel: str) -> dict: ...      # {"thumbnail_created": bool, "duration": float | None}

    def sample_frames(self, video_rel: str, out_dir_rel: str, count: int, max_edge: int = 512) -> list[str]: ...

    def studio_info(self) -> dict: ...                   # comfyui_ok, comfyui_mode, vram, queue_pending, queue_running
