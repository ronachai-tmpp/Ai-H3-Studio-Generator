"""FakeGateway สำหรับทดสอบ Series Runner (ไม่แตะ ComfyUI/ffmpeg จริง)"""

from __future__ import annotations

from pathlib import Path


class FakeGateway:
    base_url: str = "http://127.0.0.1:8188"

    def __init__(self, outputs: Path):
        self.outputs = Path(outputs)
        self.jobs: dict[str, dict] = {}
        self.submitted: list[dict] = []
        self.cancelled: list[str] = []
        self.pushed: list[str] = []
        self.input_names: set[str] = set()
        self.concat_result: dict = {"ok": True, "error": None}
        self.concat_calls: list[tuple[list[str], str]] = []
        self.extract_calls: list[tuple[str, str, str, int]] = []
        self._counter = 0

    def _touch(self, rel: str, data: bytes = b"x") -> None:
        path = self.outputs / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    # --- ฝั่งทดสอบใช้ควบคุม ---
    def finish(self, job_id: str, status: str = "DONE", error: str | None = None) -> None:
        job = self.jobs[job_id]
        job["status"] = status
        job["error"] = error
        job["finished_at"] = job["started_at"] + 5.0
        if status == "DONE":
            job["progress"] = 100
            job["video_path"] = f"videos/{job_id}.mp4"
            job["thumbnail_path"] = f"thumbnails/{job_id}.jpg"
            job["duration"] = 10.0
            self._touch(job["video_path"])
            self._touch(f"frames/{job_id}_last.jpg")
            self._touch(job["thumbnail_path"])

    def set_running(self, job_id: str, progress: int) -> None:
        self.jobs[job_id].update(status="RUNNING", progress=progress)

    def forget(self, job_id: str) -> None:
        self.jobs.pop(job_id, None)

    # --- StudioGateway ---
    def submit_job(self, *, prompt, job_type, megapixels, aspect_ratio, duration_seconds, seed,
                   reference_names=None, first_frame_name=None) -> str:
        self._counter += 1
        job_id = f"job-{self._counter}"
        self.submitted.append(dict(
            prompt=prompt, job_type=job_type, megapixels=megapixels, aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds, seed=seed, reference_names=reference_names,
            first_frame_name=first_frame_name, job_id=job_id,
        ))
        self.jobs[job_id] = dict(
            status="PENDING", progress=0, error=None, video_path=None, thumbnail_path=None,
            duration=None, started_at=1000.0 + 10.0 * self._counter, finished_at=None,
        )
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        job = self.jobs.get(job_id)
        return dict(job) if job is not None else None

    def cancel_job(self, job_id: str) -> None:
        self.cancelled.append(job_id)

    def find_output_video(self, job_id: str) -> str | None:
        rel = f"videos/{job_id}.mp4"
        return rel if (self.outputs / rel).is_file() else None

    def output_exists(self, rel_path: str) -> bool:
        return (self.outputs / rel_path).exists()

    def push_image(self, rel_path: str) -> str:
        self.pushed.append(rel_path)
        name = f"in_{len(self.pushed)}{Path(rel_path).suffix}"
        self.input_names.add(name)
        return name

    def comfy_base_url(self) -> str:
        return self.base_url

    def comfy_input_exists(self, name: str) -> bool | None:
        return name in self.input_names

    def extract_frame(self, video_rel: str, dest_rel: str, position: str = "last",
                      offset_from_end: int = 0) -> bool:
        self.extract_calls.append((video_rel, dest_rel, position, offset_from_end))
        self._touch(dest_rel)
        return True

    def concat(self, video_rels: list[str], dest_rel: str) -> dict:
        self.concat_calls.append((list(video_rels), dest_rel))
        if self.concat_result.get("ok"):
            self._touch(dest_rel)
        return dict(self.concat_result)

    def make_thumbnail(self, video_rel: str, thumb_rel: str) -> dict:
        self._touch(thumb_rel)
        return {"thumbnail_created": True, "duration": 10.0}

    def sample_frames(self, video_rel: str, out_dir_rel: str, count: int, max_edge: int = 512) -> list[str]:
        rels = [f"{out_dir_rel}/frame_{i + 1}.jpg" for i in range(count)]
        for rel in rels:
            self._touch(rel)
        return rels

    def studio_info(self) -> dict:
        return dict(comfyui_ok=True, comfyui_mode="local", vram=None, queue_pending=0, queue_running=0)
