"""
========================================
Media Processor
========================================
Description:
    สกัด metadata และสร้าง thumbnail จากไฟล์วิดีโอที่ ComfyUI generate เสร็จแล้ว

Features:
    - ค้นหา ffmpeg / ffprobe อัตโนมัติจาก:
        - environment variable
        - PATH
        - โฟลเดอร์ ComfyUI portable ที่พบบ่อย
        - ตำแหน่งติดตั้ง FFmpeg ทั่วไป
    - ใช้ ffprobe ดึง metadata ถ้ามี
    - fallback ไปใช้ ffmpeg parse stderr ถ้าไม่มี ffprobe
    - สร้าง thumbnail เป็น JPG ใน outputs/thumbnails
    - ไม่ทำให้ process ล้มเหลวถ้า ffmpeg/ffprobe ไม่มี
      แต่จะบันทึก warning ไว้ในผลลัพธ์

Notes:
    - ไฟล์วิดีโอต้นทางอยู่ที่ outputs/videos/<job-id>.mp4
    - ไฟล์ thumbnail จะอยู่ที่ outputs/thumbnails/<job-id>.jpg
    - ฝั่ง backend จะเก็บ thumbnail_path แบบสัมพัทธ์ เช่น:
      "thumbnails/<job-id>.jpg"
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from app.core import config


# ========================================
# Constants
# ========================================

PROBE_TIMEOUT_SECONDS = 15.0
THUMBNAIL_TIMEOUT_SECONDS = 30.0
THUMBNAIL_QUALITY = 3
THUMBNAIL_HEIGHT = 480

FFMPEG_ENV_KEYS = (
    "H3_FFMPEG_PATH",
    "FFMPEG_PATH",
)

FFPROBE_ENV_KEYS = (
    "H3_FFPROBE_PATH",
    "FFPROBE_PATH",
)


# ========================================
# Utility helpers
# ========================================

def _as_path(value: Any) -> Optional[Path]:
    """
    แปลงค่าให้เป็น Path อย่างปลอดภัย
    """
    if value is None:
        return None

    try:
        return Path(value)
    except Exception:
        return None


def _to_float(value: Any) -> Optional[float]:
    """
    แปลงค่าเป็น float อย่างปลอดภัย
    """
    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


def _parse_fraction(value: Any) -> Optional[float]:
    """
    แปลงค่า fps แบบ fraction เช่น 24000/1001 หรือ 24.0
    """
    if not value:
        return None

    text = str(value).strip()

    if not text or text == "0/0":
        return None

    if "/" in text:
        numerator, denominator = text.split("/", 1)
        num = _to_float(numerator)
        den = _to_float(denominator)

        if num is None or den in (None, 0):
            return None

        return num / den

    return _to_float(text)


def _candidate_roots() -> list[Path]:
    """
    รวบรวมโฟลเดอร์หลักที่อาจมี ffmpeg/ffprobe อยู่
    """
    roots: list[Path] = []

    attrs = (
        "COMFYUI_ROOT",
        "COMFYUI_APP_DIR",
        "PROJECT_ROOT",
        "BACKEND_DIR",
        "OUTPUTS_DIR",
    )

    for attr in attrs:
        path = _as_path(getattr(config, attr, None))

        if path is not None and path.exists():
            roots.append(path)

    return roots


def _common_binary_dirs(name: str) -> list[Path]:
    """
    โฟลเดอร์ทั่วไปที่คนมักติดตั้ง FFmpeg ไว้บน Windows
    """
    dirs: list[Path] = []

    exe_name = f"{name}.exe"

    candidates = [
        Path("C:/ffmpeg/bin"),
    ]

    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidates.append(Path(program_files) / "ffmpeg" / "bin")

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Microsoft" / "WinGet" / "Links")
        candidates.append(Path(local_appdata) / "Programs" / "ffmpeg" / "bin")

    for dir_path in candidates:
        try:
            if dir_path.exists():
                dirs.append(dir_path)
        except Exception:
            pass

    # กัน duplicate แบบรักษาลำดับ
    unique_dirs: list[Path] = []
    seen: set[str] = set()

    for dir_path in dirs:
        key = str(dir_path).lower()
        if key not in seen:
            seen.add(key)
            unique_dirs.append(dir_path)

    _ = exe_name
    return unique_dirs


def _find_executable(name: str) -> Optional[str]:
    """
    ค้นหา executable ของ ffmpeg หรือ ffprobe
    """
    candidates: list[str] = []

    env_keys = FFMPEG_ENV_KEYS if name == "ffmpeg" else FFPROBE_ENV_KEYS

    for key in env_keys:
        value = os.environ.get(key)
        if value:
            candidates.append(value)

    which = shutil.which(name)
    if which:
        candidates.append(which)

    exe_name = f"{name}.exe"

    for root in _candidate_roots():
        candidates.append(str(root / exe_name))
        candidates.append(str(root / name))

        # ComfyUI portable มักมี imageio-ffmpeg อยู่ใน python_embedded
        if name == "ffmpeg":
            imageio_bin_dir = (
                root
                / "python_embedded"
                / "Lib"
                / "site-packages"
                / "imageio_ffmpeg"
                / "binaries"
            )

            if imageio_bin_dir.exists():
                try:
                    for found in sorted(imageio_bin_dir.glob("ffmpeg*.exe")):
                        candidates.append(str(found))
                except Exception:
                    pass

    for dir_path in _common_binary_dirs(name):
        candidates.append(str(dir_path / exe_name))
        candidates.append(str(dir_path / name))

    for candidate in candidates:
        try:
            path = Path(candidate)
            if path.is_file():
                return str(path)
        except Exception:
            continue

    return None


def _run_command(
    command: list[str],
    timeout: float,
) -> tuple[int, str, str]:
    """
    รันคำสั่ง subprocess อย่างปลอดภัย
    """
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )

        return result.returncode, result.stdout, result.stderr

    except subprocess.TimeoutExpired:
        return 124, "", f"command timeout after {timeout} seconds"

    except FileNotFoundError as exc:
        return 127, "", str(exc)

    except Exception as exc:
        return 1, "", str(exc)


# ========================================
# Metadata extraction
# ========================================

def _probe_with_ffprobe(
    ffprobe_path: str,
    video_path: Path,
) -> tuple[dict[str, Any], list[str]]:
    """
    ใช้ ffprobe ดึง metadata เป็น JSON
    """
    command = [
        ffprobe_path,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]

    returncode, stdout, stderr = _run_command(command, PROBE_TIMEOUT_SECONDS)

    warnings: list[str] = []

    if returncode != 0:
        warnings.append(f"ffprobe returncode={returncode}: {stderr}")
        return {}, warnings

    try:
        data = json.loads(stdout)
    except Exception as exc:
        warnings.append(f"ffprobe output ไม่ใช่ JSON: {exc}")
        return {}, warnings

    metadata: dict[str, Any] = {}

    fmt = data.get("format") or {}
    streams = data.get("streams") or []

    duration = _to_float(fmt.get("duration"))

    video_stream = None
    audio_stream = None

    for stream in streams:
        if not isinstance(stream, dict):
            continue

        codec_type = stream.get("codec_type")

        if codec_type == "video" and video_stream is None:
            video_stream = stream

        if codec_type == "audio" and audio_stream is None:
            audio_stream = stream

    if video_stream:
        width = video_stream.get("width")
        height = video_stream.get("height")
        codec_name = video_stream.get("codec_name")

        fps = (
            _parse_fraction(video_stream.get("avg_frame_rate"))
            or _parse_fraction(video_stream.get("r_frame_rate"))
        )

        if width is not None:
            metadata["width"] = int(width)

        if height is not None:
            metadata["height"] = int(height)

        if codec_name:
            metadata["video_codec"] = str(codec_name)

        if fps is not None:
            metadata["fps"] = fps

        if duration is None:
            duration = _to_float(video_stream.get("duration"))

    if audio_stream:
        codec_name = audio_stream.get("codec_name")
        if codec_name:
            metadata["audio_codec"] = str(codec_name)

    if duration is not None:
        metadata["duration"] = duration

    bit_rate = _to_float(fmt.get("bit_rate"))
    if bit_rate is not None:
        metadata["bit_rate"] = bit_rate

    return metadata, warnings


def _probe_with_ffmpeg(
    ffmpeg_path: str,
    video_path: Path,
) -> tuple[dict[str, Any], list[str]]:
    """
    fallback: ใช้ ffmpeg -i แล้ว parse stderr เอา metadata คร่าวๆ
    """
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-i",
        str(video_path),
    ]

    returncode, stdout, stderr = _run_command(command, 10.0)
    output = stderr or stdout

    metadata: dict[str, Any] = {}
    warnings: list[str] = []

    if returncode == 0:
        # ffmpeg -i มัก return ไม่ใช่ 0 เพราะไม่มี output file
        # แต่ยังมีข้อมูลใน stderr ใช้ได้
        pass

    duration_match = re.search(
        r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
        output,
    )

    if duration_match:
        hours = int(duration_match.group(1))
        minutes = int(duration_match.group(2))
        seconds = float(duration_match.group(3))
        metadata["duration"] = hours * 3600 + minutes * 60 + seconds

    video_match = re.search(
        r"Stream.*?Video:.*?(\d+)x(\d+)",
        output,
    )

    if video_match:
        metadata["width"] = int(video_match.group(1))
        metadata["height"] = int(video_match.group(2))

    fps_match = re.search(
        r"(\d+(?:\.\d+)?)\s*fps",
        output,
    )

    if fps_match:
        metadata["fps"] = float(fps_match.group(1))

    if not metadata:
        warnings.append("ไม่สามารถ parse metadata จาก ffmpeg output ได้")

    return metadata, warnings


# ========================================
# Thumbnail extraction
# ========================================

def _choose_thumbnail_time(duration: Optional[float]) -> float:
    """
    เลือกเวลาสำหรับดึง thumbnail

    Description:
        - วิดีโอสั้นมาก ใช้ frame แรก
        - วิดีโอทั่วไป ใช้ประมาณ 1 วินาที หรือ 25% ของความยาว
          เพื่อเลี่ยง black frame ตอนต้นบางส่วน
    """
    if duration is None or duration <= 0:
        return 0.0

    if duration < 1.5:
        return 0.0

    return max(0.0, min(1.0, duration * 0.25))


def _extract_thumbnail_with_ffmpeg(
    ffmpeg_path: str,
    video_path: Path,
    thumbnail_path: Path,
    duration: Optional[float],
) -> tuple[bool, str]:
    """
    สร้าง thumbnail ด้วย ffmpeg
    """
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)

    thumb_time = _choose_thumbnail_time(duration)

    # scale=-2:480 หมายถึง กำหนดสูง 480px และคำนวณกว้างให้อัตโนมัติแบบหาร 2 ลงตัว
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        str(thumb_time),
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        str(THUMBNAIL_QUALITY),
        "-vf",
        f"scale=-2:{THUMBNAIL_HEIGHT}",
        str(thumbnail_path),
    ]

    returncode, stdout, stderr = _run_command(command, THUMBNAIL_TIMEOUT_SECONDS)

    if returncode == 0 and thumbnail_path.exists() and thumbnail_path.stat().st_size > 0:
        return True, ""

    # fallback: ลอง frame แรกโดยไม่ scale
    fallback_command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        "0",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        str(THUMBNAIL_QUALITY),
        str(thumbnail_path),
    ]

    returncode2, stdout2, stderr2 = _run_command(fallback_command, THUMBNAIL_TIMEOUT_SECONDS)

    if returncode2 == 0 and thumbnail_path.exists() and thumbnail_path.stat().st_size > 0:
        return True, ""

    error_text = stderr or stderr2 or stdout or stdout2
    return False, error_text


# ========================================
# Main API
# ========================================

def process_video_outputs(
    video_path: Path,
    thumbnail_path: Path,
) -> dict[str, Any]:
    """
    สกัด metadata และสร้าง thumbnail จากไฟล์วิดีโอ

    Args:
        video_path: path เต็มของไฟล์วิดีโอใน outputs/videos
        thumbnail_path: path เต็มของไฟล์ thumbnail ที่จะสร้างใน outputs/thumbnails

    Returns:
        dict containing:
            - thumbnail_created: bool
            - duration: float | None
            - width: int | None
            - height: int | None
            - fps: float | None
            - video_codec: str | None
            - audio_codec: str | None
            - bit_rate: float | None
            - file_size_bytes: int | None
            - warnings: list[str]
    """
    result: dict[str, Any] = {
        "thumbnail_created": False,
        "duration": None,
        "width": None,
        "height": None,
        "fps": None,
        "video_codec": None,
        "audio_codec": None,
        "bit_rate": None,
        "file_size_bytes": None,
        "warnings": [],
    }

    if not video_path.exists():
        result["warnings"].append(f"ไม่พบไฟล์วิดีโอ: {video_path}")
        return result

    if not video_path.is_file():
        result["warnings"].append(f"เส้นทางวิดีโอไม่ใช่ไฟล์: {video_path}")
        return result

    try:
        result["file_size_bytes"] = video_path.stat().st_size
    except Exception as exc:
        result["warnings"].append(f"อ่านขนาดไฟล์วิดีโอไม่ได้: {exc}")

    ffmpeg_path = _find_executable("ffmpeg")
    ffprobe_path = _find_executable("ffprobe")

    metadata: dict[str, Any] = {}
    warnings: list[str] = []

    if ffprobe_path:
        metadata, warnings = _probe_with_ffprobe(ffprobe_path, video_path)
    elif ffmpeg_path:
        metadata, warnings = _probe_with_ffmpeg(ffmpeg_path, video_path)
    else:
        warnings.append(
            "ไม่พบ ffmpeg/ffprobe ในเครื่อง หรือในโฟลเดอร์ ComfyUI ที่ค้นหาได้ "
            "จึงไม่สามารถสกัด metadata ได้"
        )

    for key, value in metadata.items():
        if value is not None:
            result[key] = value

    result["warnings"].extend(warnings)

    if ffmpeg_path:
        created, error_text = _extract_thumbnail_with_ffmpeg(
            ffmpeg_path=ffmpeg_path,
            video_path=video_path,
            thumbnail_path=thumbnail_path,
            duration=result.get("duration"),
        )

        if created:
            result["thumbnail_created"] = True
        else:
            result["warnings"].append(
                f"สร้าง thumbnail ไม่สำเร็จ: {error_text}"
            )
    else:
        result["warnings"].append(
            "ไม่พบ ffmpeg ในเครื่อง หรือในโฟลเดอร์ ComfyUI ที่ค้นหาได้ "
            "จึงไม่สามารถสร้าง thumbnail ได้"
        )

    return result

# ========================================
# Frame extraction (first / last) — สำหรับต่อคลิปต่อเนื่อง
# ========================================
import subprocess as _fx_sp
import tempfile as _fx_temp
from pathlib import Path as _fxPath


def _fx_run(cmd: list[str], timeout: float) -> None:
    proc = _fx_sp.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")[-800:]
        raise RuntimeError(f"ffmpeg ล้มเหลว: {err}")


def extract_frame(
    video_path,
    destination,
    position: str = "last",
    offset_from_end: int = 0,
    tail_seconds: float = 1.5,
    timeout: float = 60.0,
) -> dict:
    """
    ดึงเฟรมแรกหรือเฟรมสุดท้ายของวิดีโอออกมาเป็นรูปภาพ

    Args:
        video_path: ไฟล์วิดีโอต้นทาง
        destination: ไฟล์รูปปลายทาง (.jpg)
        position: "last" หรือ "first"
        offset_from_end: ถอยหลังจากเฟรมสุดท้ายกี่เฟรม (กัน motion blur)
                         0 = เฟรมสุดท้ายจริง, 2 = ถอยมา 2 เฟรม
        tail_seconds: ช่วงท้ายที่จะ decode (วินาที)
        timeout: เวลาสูงสุดต่อคำสั่ง ffmpeg

    Returns:
        dict: created, path, position, offset_from_end, error
    """
    video_path = _fxPath(video_path)
    destination = _fxPath(destination)

    ffmpeg = _find_executable("ffmpeg")
    if not ffmpeg:
        return {"created": False, "error": "ไม่พบ ffmpeg"}

    if not video_path.exists():
        return {"created": False, "error": f"ไม่พบไฟล์วิดีโอ: {video_path}"}

    destination.parent.mkdir(parents=True, exist_ok=True)
    position = (position or "last").strip().lower()
    offset_from_end = max(0, int(offset_from_end or 0))

    try:
        if position == "first":
            _fx_run(
                [ffmpeg, "-y", "-i", str(video_path),
                 "-frames:v", "1", "-q:v", "2", str(destination)],
                timeout,
            )
        elif offset_from_end == 0:
            # เฟรมสุดท้ายจริง: seek ใกล้จบ + เขียนทับทุกเฟรม
            _fx_run(
                [ffmpeg, "-y", "-sseof", f"-{tail_seconds}", "-i", str(video_path),
                 "-update", "1", "-q:v", "2", str(destination)],
                timeout,
            )
        else:
            # ถอยหลัง N เฟรม: แตกเฟรมช่วงท้ายแล้วเลือกตัวที่ต้องการ
            with _fx_temp.TemporaryDirectory() as tmp:
                pattern = _fxPath(tmp) / "%05d.png"
                _fx_run(
                    [ffmpeg, "-y", "-sseof", f"-{tail_seconds}", "-i", str(video_path),
                     "-fps_mode", "passthrough", str(pattern)],
                    timeout,
                )
                frames = sorted(_fxPath(tmp).glob("*.png"))
                if not frames:
                    return {"created": False, "error": "ไม่พบเฟรมในช่วงท้ายวิดีโอ"}
                index = max(0, len(frames) - 1 - offset_from_end)
                _fx_run(
                    [ffmpeg, "-y", "-i", str(frames[index]),
                     "-q:v", "2", str(destination)],
                    timeout,
                )

        created = destination.exists() and destination.stat().st_size > 0
        return {
            "created": created,
            "path": str(destination),
            "position": position,
            "offset_from_end": offset_from_end,
            "error": None if created else "สร้างไฟล์รูปไม่สำเร็จ",
        }
    except Exception as exc:
        return {"created": False, "error": str(exc)}

# ========================================
# Frame extraction (first / last) — สำหรับต่อคลิปต่อเนื่อง
# ========================================
import subprocess as _fx_sp
import tempfile as _fx_temp
from pathlib import Path as _fxPath
from typing import Optional

from app.core import config as _fx_config


def _find_ffmpeg() -> Optional[str]:
    """
    ค้นหา ffmpeg จากหลายที่:
    1. config.json (ffmpeg_path)
    2. PATH environment
    3. Windows standard paths
    4. Bundled ใน backend/

    Returns:
        path ของ ffmpeg executable หรือ None ถ้าไม่พบ
    """
    # 1. จาก config
    if _fx_config.FFMPEG_PATH:
        ffmpeg_path = _fxPath(_fx_config.FFMPEG_PATH)
        if ffmpeg_path.exists() and ffmpeg_path.is_file():
            return str(ffmpeg_path)
        print(f"[media_processor] ffmpeg_path ใน config ไม่พบ: {ffmpeg_path}")

    # 2. จาก PATH
    try:
        result = _fx_sp.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return "ffmpeg"
    except (FileNotFoundError, _fx_sp.TimeoutExpired):
        pass

    # 3. จาก Windows standard paths
    for path_str in _fx_config.FFMPEG_SEARCH_PATHS:
        path = _fxPath(path_str)
        if path.exists() and path.is_file():
            return str(path)

    return None


def _fx_run(cmd: list[str], timeout: float) -> None:
    """รันคำสั่ง ffmpeg พร้อม timeout"""
    proc = _fx_sp.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace")[-800:]
        raise RuntimeError(f"ffmpeg ล้มเหลว: {err}")


def extract_frame(
    video_path,
    destination,
    position: str = "last",
    offset_from_end: int = 0,
    tail_seconds: float = 1.5,
    timeout: float = None,
) -> dict:
    """
    ดึงเฟรมแรกหรือเฟรมสุดท้ายของวิดีโอออกมาเป็นรูปภาพ

    Args:
        video_path: ไฟล์วิดีโอต้นทาง
        destination: ไฟล์รูปปลายทาง (.jpg)
        position: "last" หรือ "first"
        offset_from_end: ถอยหลังจากเฟรมสุดท้ายกี่เฟรม (กัน motion blur)
                         0 = เฟรมสุดท้ายจริง, 2 = ถอยมา 2 เฟรม
        tail_seconds: ช่วงท้ายที่จะ decode (วินาที)
        timeout: เวลาสูงสุดต่อคำสั่ง ffmpeg

    Returns:
        dict: created, path, position, offset_from_end, error
    """
    if timeout is None:
        timeout = _fx_config.FFMPEG_TIMEOUT_SECONDS

    video_path = _fxPath(video_path)
    destination = _fxPath(destination)

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return {
            "created": False,
            "error": "ไม่พบ ffmpeg — ติดตั้ง ffmpeg หรือตั้งค่า ffmpeg_path ใน backend/config.json",
        }

    if not video_path.exists():
        return {"created": False, "error": f"ไม่พบไฟล์วิดีโอ: {video_path}"}

    destination.parent.mkdir(parents=True, exist_ok=True)
    position = (position or "last").strip().lower()
    offset_from_end = max(0, int(offset_from_end or 0))

    try:
        if position == "first":
            _fx_run(
                [ffmpeg, "-y", "-i", str(video_path),
                 "-frames:v", "1", "-q:v", "2", str(destination)],
                timeout,
            )
        elif offset_from_end == 0:
            # เฟรมสุดท้ายจริง: seek ใกล้จบ + เขียนทับทุกเฟรม
            _fx_run(
                [ffmpeg, "-y", "-sseof", f"-{tail_seconds}", "-i", str(video_path),
                 "-update", "1", "-q:v", "2", str(destination)],
                timeout,
            )
        else:
            # ถอยหลัง N เฟรม: แตกเฟรมช่วงท้ายแล้วเลือกตัวที่ต้องการ
            with _fx_temp.TemporaryDirectory() as tmp:
                pattern = _fxPath(tmp) / "%05d.png"
                _fx_run(
                    [ffmpeg, "-y", "-sseof", f"-{tail_seconds}", "-i", str(video_path),
                     "-fps_mode", "passthrough", str(pattern)],
                    timeout,
                )
                frames = sorted(_fxPath(tmp).glob("*.png"))
                if not frames:
                    return {"created": False, "error": "ไม่พบเฟรมในช่วงท้ายวิดีโอ"}
                index = max(0, len(frames) - 1 - offset_from_end)
                _fx_run(
                    [ffmpeg, "-y", "-i", str(frames[index]),
                     "-q:v", "2", str(destination)],
                    timeout,
                )

        created = destination.exists() and destination.stat().st_size > 0
        return {
            "created": created,
            "path": str(destination),
            "position": position,
            "offset_from_end": offset_from_end,
            "error": None if created else "สร้างไฟล์รูปไม่สำเร็จ",
        }
    except Exception as exc:
        return {"created": False, "error": str(exc)}

# ========================================
# Video concat (merge clips) — รวมคลิปที่ chain แล้ว
# ========================================
import json as _fx_json


def probe_video_streams(video_path, timeout: float = 30.0) -> dict | None:
    """
    อ่านข้อมูล stream หลักของวิดีโอ เพื่อตัดสินว่า concat แบบ copy ได้ไหม

    Returns:
        dict ข้อมูล stream หรือ None ถ้าอ่านไม่ได้
    """
    ffprobe = _find_executable("ffprobe")
    if not ffprobe:
        return None

    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate",
        "-of", "json",
        str(video_path),
    ]

    try:
        proc = _fx_sp.run(cmd, capture_output=True, timeout=timeout)
        if proc.returncode != 0:
            return None
        data = _fx_json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except Exception:
        return None

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if not video:
        return None

    return {
        "video_codec": video.get("codec_name"),
        "width": video.get("width"),
        "height": video.get("height"),
        "fps": video.get("r_frame_rate"),
        "has_audio": audio is not None,
        "audio_codec": audio.get("codec_name") if audio else None,
        "sample_rate": audio.get("sample_rate") if audio else None,
    }


def _concat_list_line(path) -> str:
    """สร้างบรรทัด file '...' สำหรับ concat demuxer พร้อม escape"""
    p = str(path).replace("\\", "/")
    p = p.replace("'", "'\\''")
    return f"file '{p}'"


def concat_videos(video_paths, destination, timeout: float = 900.0) -> dict:
    """
    รวมหลายคลิปเป็นไฟล์เดียวด้วย ffmpeg

    Description:
        - ถ้าทุกคลิปมี codec/ขนาด/fps/audio ตรงกัน → ใช้ concat demuxer + -c copy
          (เร็วมาก ไม่สูญเสียคุณภาพ)
        - ถ้าไม่ตรงกัน → re-encode พร้อม normalize ขนาด/fps/sample rate
          ให้เท่ากับคลิปแรกอัตโนมัติ

    Args:
        video_paths: รายการ path วิดีโอเรียงลำดับ
        destination: ไฟล์ปลายทาง (.mp4)
        timeout: เวลาสูงสุด

    Returns:
        dict: ok, mode ("copy" | "reencode"), path, error
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return {"ok": False, "error": "ไม่พบ ffmpeg — ติดตั้งหรือตั้งค่า ffmpeg_path ก่อน"}

    paths = [_fxPath(p) for p in video_paths]

    if len(paths) < 2:
        return {"ok": False, "error": "ต้องเลือกอย่างน้อย 2 คลิป"}

    missing = next((str(p) for p in paths if not p.is_file()), None)
    if missing:
        return {"ok": False, "error": f"ไม่พบไฟล์วิดีโอ: {missing}"}

    probes = [probe_video_streams(p) for p in paths]
    if any(pr is None for pr in probes):
        return {"ok": False, "error": "อ่านข้อมูล stream ของบางคลิปไม่สำเร็จ"}

    if any(not pr["has_audio"] for pr in probes):
        return {
            "ok": False,
            "error": "พบคลิปที่ไม่มีแทร็กเสียง — ปัจจุบันรองรับเฉพาะคลิปที่มีทั้งภาพและเสียง",
        }

    destination = _fxPath(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)

    def sig(pr: dict):
        return (
            pr["video_codec"], pr["width"], pr["height"],
            pr["fps"], pr["audio_codec"], pr["sample_rate"],
        )

    mode = "copy" if all(sig(pr) == sig(probes[0]) for pr in probes) else "reencode"

    try:
        if mode == "copy":
            list_path = destination.with_suffix(".concat.txt")
            list_path.write_text(
                "\n".join(_concat_list_line(p) for p in paths) + "\n",
                encoding="utf-8",
            )
            cmd = [
                ffmpeg, "-y", "-f", "concat", "-safe", "0",
                "-i", str(list_path), "-c", "copy", str(destination),
            ]
            try:
                _fx_run(cmd, timeout)
            finally:
                list_path.unlink(missing_ok=True)
        else:
            base = probes[0]
            width = base["width"]
            height = base["height"]
            fps = base["fps"] or "24"
            rate = base["sample_rate"] or "48000"

            parts = []
            for i in range(len(probes)):
                parts.append(
                    f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}];"
                    f"[{i}:a]aresample={rate}[a{i}];"
                )
            concat_in = "".join(f"[v{i}][a{i}]" for i in range(len(probes)))
            filter_complex = (
                "".join(parts)
                + f"{concat_in}concat=n={len(probes)}:v=1:a=1[v][a]"
            )

            cmd = [ffmpeg, "-y"]
            for p in paths:
                cmd += ["-i", str(p)]
            cmd += [
                "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-c:a", "aac", "-b:a", "192k",
                str(destination),
            ]
            _fx_run(cmd, timeout)

        ok = destination.exists() and destination.stat().st_size > 0
        return {
            "ok": ok,
            "mode": mode,
            "path": str(destination),
            "error": None if ok else "สร้างไฟล์รวมไม่สำเร็จ",
        }
    except Exception as exc:
        return {"ok": False, "mode": mode, "error": str(exc)}

# ========================================
# VLM helpers: duration + สุ่มเฟรมจากวิดีโอ
# ========================================

def probe_duration_seconds(video_path, timeout: float = 30.0):
    """อ่านความยาววิดีโอ (วินาที) ด้วย ffprobe"""
    ffprobe = _find_executable("ffprobe")
    if not ffprobe:
        return None

    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(video_path),
    ]

    try:
        proc = _fx_sp.run(cmd, capture_output=True, timeout=timeout)
        if proc.returncode != 0:
            return None
        return float(proc.stdout.decode("utf-8", errors="replace").strip())
    except Exception:
        return None


def extract_video_frames(video_path, out_dir, max_frames: int = 6, timeout: float = 120.0):
    """
    สุ่มเฟรมจากวิดีโอให้กระจายทั่วทั้งคลิป (ไม่ใช่แค่ต้นคลิป)
    แล้วคืนรายการ path ของรูปที่สร้าง
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ไม่พบ ffmpeg — ติดตั้งหรือตั้งค่า ffmpeg_path ก่อน")

    video_path = _fxPath(video_path)
    out_dir = _fxPath(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    max_frames = max(1, int(max_frames))
    duration = probe_duration_seconds(video_path) or 0.0
    rate = (max_frames / duration) if duration > 0 else 1.0

    pattern = out_dir / "frame_%03d.jpg"
    cmd = [
        ffmpeg, "-y", "-i", str(video_path),
        "-vf", f"fps={rate:.6f}",
        "-frames:v", str(max_frames),
        "-q:v", "2",
        str(pattern),
    ]
    _fx_run(cmd, timeout)

    return sorted(out_dir.glob("frame_*.jpg"))