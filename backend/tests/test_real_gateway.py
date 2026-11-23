from __future__ import annotations

import shutil
import subprocess

import pytest

from app.core import config
from app.services import media_processor
from app.services.series_runtime import RealGateway


class StubQueue:
    def __init__(self): self.created = []
    def create_job(self, **kw): self.created.append(kw); return {"id": "abc"}
    def get_job(self, job_id): return None
    def cancel_job(self, job_id): return None


def test_submit_job_maps_to_queue_arguments(outputs):
    q = StubQueue(); g = RealGateway(queue=q, outputs_dir=outputs)
    assert g.submit_job(prompt="p", job_type="FL2VA", megapixels=0.35,
                        aspect_ratio="9:16 (Portrait Widescreen)", duration_seconds=8, seed=-1,
                        first_frame_name="in.jpg") == "abc"
    kw = q.created[0]
    assert (kw["type_"], kw["resolution"], kw["duration_seconds"], kw["aspect_ratio"], kw["first_frame_name"]) == \
           ("FL2VA", "0.35 MP", 8, "9:16 (Portrait Widescreen)", "in.jpg")


def test_megapixel_string_parses_back(outputs):
    from app.services.h3_service import _megapixels_for_resolution
    assert _megapixels_for_resolution("0.35 MP") == 0.35


def test_find_output_video(outputs):
    g = RealGateway(queue=StubQueue(), outputs_dir=outputs)
    assert g.find_output_video("j1") is None
    (outputs / "videos" / "j1.mp4").write_bytes(b"v")
    assert g.find_output_video("j1") == "videos/j1.mp4" and g.output_exists("videos/j1.mp4")


def test_studio_info_survives_comfyui_down(outputs, monkeypatch):
    from app.services import comfyui_client
    monkeypatch.setattr(comfyui_client, "get_system_stats", lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert RealGateway(queue=StubQueue(), outputs_dir=outputs).studio_info()["comfyui_ok"] is False


def test_comfy_input_exists_reads_config_at_call_time(outputs, tmp_path, monkeypatch):
    g = RealGateway(queue=StubQueue(), outputs_dir=outputs)
    (tmp_path / "a.jpg").write_bytes(b"x")
    monkeypatch.setattr(config, "COMFYUI_IS_REMOTE", False)
    monkeypatch.setattr(config, "COMFYUI_INPUT_DIR", tmp_path)
    assert g.comfy_input_exists("a.jpg") is True and g.comfy_input_exists("b.jpg") is False
    monkeypatch.setattr(config, "COMFYUI_IS_REMOTE", True)
    assert g.comfy_input_exists("a.jpg") is None


def test_mcp_allow_lan_is_bool():
    assert isinstance(config.MCP_ALLOW_LAN, bool)


def test_sample_frames_caps_longer_edge(outputs, tmp_path):
    ffmpeg = media_processor._find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ไม่พบ ffmpeg")
    video = outputs / "videos" / "clip.mp4"
    subprocess.run([ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=24:duration=1",
                    "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True)
    g = RealGateway(queue=StubQueue(), outputs_dir=outputs)
    rels = g.sample_frames("videos/clip.mp4", "series/x/review", 3, max_edge=512)
    assert 1 <= len(rels) <= 3
    for rel in rels:
        assert rel.startswith("series/x/review/") and (outputs / rel).is_file()
        edges = _image_size(ffmpeg, outputs / rel)
        assert max(edges) <= 512 and max(edges) > 0


def _image_size(ffmpeg: str, path) -> tuple[int, int]:
    probe = shutil.which("ffprobe") or str(media_processor._find_executable("ffprobe"))
    out = subprocess.run([probe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout.strip()
    w, h = out.split(",")
    return int(w), int(h)
