"""
ทดสอบบั๊กของโค้ดเดิมที่เจอระหว่างรันจริง
- extract_frame แบบถอยหลัง N เฟรม ต้องใช้ได้กับ ffmpeg รุ่นใหม่ (ไม่มี -vsync แล้ว)
- print ภาษาไทยต้องไม่ทำให้ backend พังเมื่อ stdout ไม่ใช่ UTF-8 (ถูกส่งลงไฟล์/pipe)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import media_processor

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _make_clip(ffmpeg: str, path: Path) -> None:
    subprocess.run(
        [ffmpeg, "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=24:duration=2",
         "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True,
    )


def test_extract_frame_with_offset_from_end(tmp_path):
    ffmpeg = media_processor._find_ffmpeg()
    if not ffmpeg:
        pytest.skip("ไม่พบ ffmpeg")
    video = tmp_path / "clip.mp4"
    _make_clip(ffmpeg, video)
    dest = tmp_path / "frames" / "clip_last_m3.jpg"

    result = media_processor.extract_frame(
        video_path=video, destination=dest, position="last", offset_from_end=3,
    )

    assert result["created"] is True, result.get("error")
    assert dest.is_file() and dest.stat().st_size > 0
    assert result["offset_from_end"] == 3


def test_thai_print_survives_non_utf8_stdout():
    """จำลอง stdout ที่เป็น cp1252 (เหมือนตอนส่ง log ลงไฟล์บน Windows) แล้ว import แอป + print ไทย"""
    env = dict(os.environ)
    env.pop("PYTHONUTF8", None)
    env["PYTHONIOENCODING"] = "cp1252"
    proc = subprocess.run(
        [sys.executable, "-c", "import app.main; print('ดึง last frame สำเร็จ')"],
        cwd=BACKEND_DIR, env=env, capture_output=True, timeout=120,
    )

    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")[-800:]
    assert "ดึง last frame สำเร็จ" in proc.stdout.decode("utf-8")
