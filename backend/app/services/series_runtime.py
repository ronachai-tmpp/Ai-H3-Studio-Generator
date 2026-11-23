"""ต่อ Series Runner เข้ากับ Studio จริง: RealGateway + singleton ของกระบวนการ

อ่านค่า config ตอนเรียกใช้เสมอ (ไม่เก็บตอน import) เพราะหน้า Settings เปลี่ยนการเชื่อมต่อ ComfyUI ได้ขณะแอปรัน
"""

from __future__ import annotations

from pathlib import Path

from app.core import config
from app.services import comfyui_client, media_processor, prompt_enhance_service
from app.services.queue_service import queue_service
from app.services.series_runner import SeriesRunner
from app.services.series_service import SeriesService
from app.services.series_store import SeriesStore


class RealGateway:
    """StudioGateway ตัวจริง: คิวงาน, ComfyUI และ ffmpeg ของแอป"""

    def __init__(self, queue=queue_service, outputs_dir: Path | None = None):
        self._queue = queue
        self._outputs_dir = outputs_dir

    @property
    def outputs_dir(self) -> Path:
        return self._outputs_dir or config.OUTPUTS_DIR

    def _abs(self, rel_path: str) -> Path:
        return self.outputs_dir / rel_path

    # ---------- คิวงาน ----------
    def submit_job(self, *, prompt: str, job_type: str, megapixels: float, aspect_ratio: str,
                   duration_seconds: int, seed: int,
                   reference_names: list[str] | None = None,
                   first_frame_name: str | None = None) -> str:
        job = self._queue.create_job(
            prompt=prompt,
            type_=job_type,
            resolution=f"{megapixels} MP",
            steps=6,
            seed=seed,
            duration_seconds=duration_seconds,
            aspect_ratio=aspect_ratio,
            reference_names=reference_names,
            first_frame_name=first_frame_name,
        )
        return job["id"]

    def get_job(self, job_id: str) -> dict | None:
        return self._queue.get_job(job_id)

    def cancel_job(self, job_id: str) -> None:
        self._queue.cancel_job(job_id)

    # ---------- ไฟล์ผลลัพธ์ ----------
    def find_output_video(self, job_id: str) -> str | None:
        for path in sorted((self.outputs_dir / "videos").glob(f"{job_id}.*")):
            if path.is_file():
                return f"videos/{path.name}"
        return None

    def output_exists(self, rel_path: str) -> bool:
        return self._abs(rel_path).is_file()

    # ---------- ComfyUI ----------
    def push_image(self, rel_path: str) -> str:
        return prompt_enhance_service.push_image_to_comfyui(self._abs(rel_path))

    def comfy_base_url(self) -> str:
        return config.COMFYUI_API_BASE_URL

    def comfy_input_exists(self, name: str) -> bool | None:
        if config.COMFYUI_IS_REMOTE:
            return None
        return (Path(config.COMFYUI_INPUT_DIR) / name).is_file()

    # ---------- ffmpeg ----------
    def extract_frame(self, video_rel: str, dest_rel: str, position: str = "last",
                      offset_from_end: int = 0) -> bool:
        result = media_processor.extract_frame(
            self._abs(video_rel), self._abs(dest_rel),
            position=position, offset_from_end=offset_from_end,
        )
        return bool(result.get("created"))

    def concat(self, video_rels: list[str], dest_rel: str) -> dict:
        return media_processor.concat_videos([self._abs(r) for r in video_rels], self._abs(dest_rel))

    def make_thumbnail(self, video_rel: str, thumb_rel: str) -> dict:
        return media_processor.process_video_outputs(self._abs(video_rel), self._abs(thumb_rel))

    def sample_frames(self, video_rel: str, out_dir_rel: str, count: int, max_edge: int = 512) -> list[str]:
        """สุ่มเฟรมกระจายทั้งคลิป แล้วย่อให้ด้านยาวสุดไม่เกิน max_edge (ไม่ขยายรูปที่เล็กกว่า)"""
        ffmpeg = media_processor._find_ffmpeg()
        if not ffmpeg:
            raise RuntimeError("ไม่พบ ffmpeg — ติดตั้งหรือตั้งค่า ffmpeg_path ก่อน")
        video = self._abs(video_rel)
        out_dir = self._abs(out_dir_rel)
        out_dir.mkdir(parents=True, exist_ok=True)

        count = max(1, int(count))
        duration = media_processor.probe_duration_seconds(video) or 0.0
        rate = (count / duration) if duration > 0 else 1.0
        scale = (f"scale='min({max_edge},iw)':'min({max_edge},ih)'"
                 ":force_original_aspect_ratio=decrease")
        media_processor._fx_run([
            ffmpeg, "-y", "-i", str(video),
            "-vf", f"fps={rate:.6f},{scale}",
            "-frames:v", str(count), "-q:v", "3",
            str(out_dir / "frame_%03d.jpg"),
        ], config.FFMPEG_TIMEOUT_SECONDS * 4)
        return [f"{out_dir_rel.rstrip('/')}/{p.name}" for p in sorted(out_dir.glob("frame_*.jpg"))]

    # ---------- สถานะ ----------
    def studio_info(self) -> dict:
        info: dict = {"comfyui_ok": False, "comfyui_mode": config.COMFYUI_MODE, "vram": None,
                      "queue_pending": 0, "queue_running": 0}
        try:
            stats = comfyui_client.get_system_stats()
            devices = stats.get("devices") or []
            info["comfyui_ok"] = True
            if devices:
                info["vram"] = {"total": devices[0].get("vram_total"), "free": devices[0].get("vram_free")}
        except Exception:
            pass
        try:
            jobs = self._queue.list_jobs() if hasattr(self._queue, "list_jobs") else []
            info["queue_pending"] = sum(1 for j in jobs if j.get("status") == "PENDING")
            info["queue_running"] = sum(1 for j in jobs if j.get("status") == "RUNNING")
        except Exception:
            pass
        return info


series_store = SeriesStore(config.OUTPUTS_DIR / "series")
series_gateway = RealGateway()
series_service = SeriesService(
    series_store, series_gateway, config.OUTPUTS_DIR,
    config.ALLOWED_IMAGE_EXTENSIONS, config.UPLOAD_MAX_FILE_SIZE_BYTES,
    allow_external_images=not config.MCP_ALLOW_LAN,
)
series_runner = SeriesRunner(series_store, series_gateway)
