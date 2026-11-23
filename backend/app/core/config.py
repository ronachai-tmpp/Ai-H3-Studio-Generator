r"""
========================================
Backend Configuration
========================================
Description:
    Central configuration file for MiniMax H3 Studio backend.

    This file loads settings from:
    1. backend/config.json
    2. environment variables

    Environment variables override config.json.

    Main responsibilities:
    - Resolve ComfyUI portable/custom paths
    - Resolve ComfyUI input/output/model directories
    - Store MiniMax H3 model filenames
    - Store Pika H3 Flex LoRA filename
    - Store workflow template path
    - Store upload restrictions
    - Preserve existing LLM/Gemma settings

Design notes:
    - ComfyUI portable often has this structure:
        D:\ComfyUI_windows_portable\ComfyUI\models
        D:\ComfyUI_windows_portable\ComfyUI\input
        D:\ComfyUI_windows_portable\ComfyUI\output

    - Some users may install ComfyUI directly at:
        D:\ComfyUI

    - Therefore config auto-detects whether COMFYUI_ROOT contains
      a nested "ComfyUI" folder.

    - LoadImage nodes in ComfyUI usually require filename only,
      not absolute path. Uploaded reference files must be stored
      inside COMFYUI_INPUT_DIR.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


# ========================================
# Base project paths
# ========================================

BASE_DIR = Path(__file__).resolve().parents[3]
BACKEND_DIR = BASE_DIR / "backend"
CONFIG_JSON_PATH = BACKEND_DIR / "config.json"


# ========================================
# config.json loader
# ========================================

def _read_config_json() -> tuple[dict[str, Any], str | None]:
    """
    อ่าน config.json จาก backend folder

    Returns:
        tuple:
            - config dict
            - error message or None
    """
    if not CONFIG_JSON_PATH.exists():
        return {}, None

    try:
        with CONFIG_JSON_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {}, "config.json root must be a JSON object"

        return data, None

    except Exception as exc:
        return {}, str(exc)


_CONFIG_JSON, CONFIG_JSON_ERROR = _read_config_json()


def _get(key: str, default: Any) -> Any:
    """
    อ่านค่า config โดยลำดับความสำคัญ:
    1. environment variable ชื่อตัวพิมพ์ใหญ่
    2. config.json
    3. default

    Empty environment variable is ignored.
    Empty string in config.json is treated as "use default" for path-like values.
    """
    env_key = key.upper()

    if env_key in os.environ:
        env_value = os.environ[env_key]
        if env_value != "":
            return env_value

    return _CONFIG_JSON.get(key, default)


def _safe_resolve(path: Path) -> Path:
    """
    Resolve path อย่างปลอดภัย

    Description:
        บางกรณี path ยังไม่มีอยู่จริง หรือ drive ไม่มีอยู่
        resolve() อาจ throw OSError ในบางสภาพแวดล้อม
        จึง fallback เป็น absolute()
    """
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _path_value(key: str, default: str) -> Path:
    """
    อ่านค่า path จาก config/env

    Args:
        key: config key
        default: default path string

    Returns:
        Resolved Path object
    """
    raw = _get(key, default)
    raw_str = str(raw).strip()

    if not raw_str:
        raw_str = default

    expanded = os.path.expandvars(raw_str)
    return _safe_resolve(Path(expanded).expanduser())


def _int_value(key: str, default: int) -> int:
    """
    อ่านค่า integer จาก config/env
    """
    raw = _get(key, default)

    try:
        return int(float(str(raw).strip()))
    except Exception:
        return default


def _float_value(key: str, default: float) -> float:
    """
    อ่านค่า float จาก config/env
    """
    raw = _get(key, default)

    try:
        return float(str(raw).strip())
    except Exception:
        return default


def _list_value(key: str, default: list[str]) -> list[str]:
    """
    อ่านค่า list จาก config/env

    Supported formats:
    - JSON array: [".png", ".jpg"]
    - comma-separated string: ".png,.jpg"
    """
    raw = _get(key, default)

    if isinstance(raw, list):
        return [str(item).strip().lower() for item in raw if str(item).strip()]

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return default

        return [item.strip().lower() for item in text.split(",") if item.strip()]

    return default


# ========================================
# Project root paths
# ========================================

PROJECT_ROOT = BASE_DIR

# Local project models folder, mainly for future LLM/Gemma GGUF
PROJECT_MODELS_DIR = _path_value("project_models_dir", str(BASE_DIR / "models"))

# Local outputs folder for H3 Studio metadata/cache if needed
OUTPUTS_DIR = _path_value("outputs_dir", str(BASE_DIR / "outputs"))

# LLM models folder used by existing llm_service.py
LLM_MODELS_DIR = _path_value("llm_models_dir", str(PROJECT_MODELS_DIR / "llm"))


# ========================================
# ComfyUI root detection
# ========================================

COMFYUI_ROOT = _path_value("comfyui_root", r"D:\ComfyUI_windows_portable")

_raw_comfyui_app_dir = _get("comfyui_app_dir", "")

if str(_raw_comfyui_app_dir).strip():
    COMFYUI_APP_DIR = _path_value("comfyui_app_dir", str(COMFYUI_ROOT))
else:
    candidate = COMFYUI_ROOT / "ComfyUI"

    # Portable ComfyUI usually has nested ComfyUI folder
    if candidate.exists() and (candidate / "models").exists():
        COMFYUI_APP_DIR = _safe_resolve(candidate)
    else:
        COMFYUI_APP_DIR = COMFYUI_ROOT


# ========================================
# ComfyUI directories
# ========================================

COMFYUI_INPUT_DIR = _path_value("comfyui_input_dir", str(COMFYUI_APP_DIR / "input"))
COMFYUI_OUTPUT_DIR = _path_value("comfyui_output_dir", str(COMFYUI_APP_DIR / "output"))
COMFYUI_MODELS_DIR = _path_value("comfyui_models_dir", str(COMFYUI_APP_DIR / "models"))

COMFYUI_DIFFUSION_MODELS_DIR = COMFYUI_MODELS_DIR / "diffusion_models"
COMFYUI_TEXT_ENCODERS_DIR = COMFYUI_MODELS_DIR / "text_encoders"
COMFYUI_VAE_DIR = COMFYUI_MODELS_DIR / "vae"
COMFYUI_LORAS_DIR = COMFYUI_MODELS_DIR / "loras"
COMFYUI_CUSTOM_NODES_DIR = COMFYUI_APP_DIR / "custom_nodes"


# ========================================
# ComfyUI API
# ========================================

COMFYUI_API_BASE_URL = str(
    _get("comfyui_api_base_url", "http://127.0.0.1:8188")
).strip().rstrip("/")

COMFYUI_REQUEST_TIMEOUT_SECONDS = _float_value(
    "comfyui_request_timeout_seconds",
    10.0,
)

COMFYUI_WEBSOCKET_TIMEOUT_SECONDS = _float_value(
    "comfyui_websocket_timeout_seconds",
    30.0,
)


# ========================================
# Upload settings
# ========================================

UPLOAD_MAX_FILE_SIZE_MB = _int_value("upload_max_file_size_mb", 100)
UPLOAD_MAX_FILE_SIZE_BYTES = UPLOAD_MAX_FILE_SIZE_MB * 1024 * 1024

ALLOWED_IMAGE_EXTENSIONS = _list_value(
    "allowed_image_extensions",
    [
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
    ],
)

ALLOWED_VIDEO_EXTENSIONS = _list_value(
    "allowed_video_extensions",
    [
        ".mp4",
        ".webm",
        ".mov",
        ".avi",
        ".mkv",
    ],
)

ALLOWED_AUDIO_EXTENSIONS = _list_value(
    "allowed_audio_extensions",
    [
        ".wav",
        ".mp3",
        ".flac",
        ".ogg",
        ".m4a",
    ],
)

ALLOWED_REFERENCE_EXTENSIONS = sorted(
    set(ALLOWED_IMAGE_EXTENSIONS + ALLOWED_VIDEO_EXTENSIONS + ALLOWED_AUDIO_EXTENSIONS)
)


# ========================================
# Workflow template settings
# ========================================

WORKFLOW_TEMPLATE_DIR = _path_value(
    "workflow_template_dir",
    str(BACKEND_DIR / "workflows"),
)

REF2VA_WORKFLOW_FILENAME = str(
    _get(
        "ref2va_workflow_filename",
        "minimax_h3_ref2va_pika_flex.api.json",
    )
).strip()

T2V_WORKFLOW_FILENAME = str(
    _get(
        "t2v_workflow_filename",
        "minimax_h3_t2v_pika_flex.api.json",
    )
).strip()

REF2VA_WORKFLOW_PATH = WORKFLOW_TEMPLATE_DIR / REF2VA_WORKFLOW_FILENAME
T2V_WORKFLOW_PATH = WORKFLOW_TEMPLATE_DIR / T2V_WORKFLOW_FILENAME


# ========================================
# MiniMax H3 / Pika H3 Flex model filenames
# ========================================

DIFFUSION_MODEL_FILENAME = str(
    _get(
        "diffusion_model_filename",
        "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    )
).strip()

TEXT_ENCODER_FILENAME = str(
    _get(
        "text_encoder_filename",
        "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    )
).strip()

VIDEO_VAE_FILENAME = str(
    _get(
        "video_vae_filename",
        "minimax_h3_video_vae_int8_convrot.safetensors",
    )
).strip()

AUDIO_VAE_FILENAME = str(
    _get(
        "audio_vae_filename",
        "minimax_h3_audio_vae_fp32.safetensors",
    )
).strip()

LORA_FILENAME = str(
    _get(
        "lora_filename",
        "pika_h3_flex_ref2va_v1_bf16.safetensors",
    )
).strip()

T2V_DIFFUSION_MODEL_FILENAME = str(
    _get(
        "t2v_diffusion_model_filename",
        "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    )
).strip()

T2V_LORA_FILENAME = str(
    _get(
        "t2v_lora_filename",
        "pika_h3_flex_fl2va_v1_bf16.safetensors",
    )
).strip()


# ========================================
# LLM / Gemma settings preserved from previous step
# ========================================

LLM_MODEL_FILENAME = str(
    _get("llm_model_filename", "gemma-3-4b-it-Q4_K_M.gguf")
).strip()

LLM_N_GPU_LAYERS = _int_value("llm_n_gpu_layers", -1)
LLM_N_CTX = _int_value("llm_n_ctx", 4096)
LLM_IDLE_TIMEOUT_SECONDS = _int_value("llm_idle_timeout_seconds", 300)

LLM_TEMPERATURE = _float_value("llm_temperature", 0.7)
LLM_TOP_P = _float_value("llm_top_p", 0.9)
LLM_REPEAT_PENALTY = _float_value("llm_repeat_penalty", 1.1)
LLM_MAX_TOKENS = _int_value("llm_max_tokens", 512)


# ========================================
# Helper functions for diagnostics
# ========================================

def _file_info(path: Path) -> dict[str, Any]:
    """
    Return JSON-friendly info about a file path.
    """
    exists = path.exists()
    is_file = path.is_file() if exists else False

    size_mb: float | None = None

    if exists and is_file:
        try:
            size_mb = round(path.stat().st_size / (1024 * 1024), 2)
        except OSError:
            size_mb = None

    return {
        "path": str(path),
        "filename": path.name,
        "exists": exists,
        "is_file": is_file,
        "size_mb": size_mb,
    }


def _dir_info(path: Path) -> dict[str, Any]:
    """
    Return JSON-friendly info about a directory path.
    """
    exists = path.exists()
    is_dir = path.is_dir() if exists else False

    free_gb: float | None = None

    if exists and is_dir:
        try:
            usage = shutil.disk_usage(path)
            free_gb = round(usage.free / (1024 ** 3), 2)
        except OSError:
            free_gb = None

    return {
        "path": str(path),
        "exists": exists,
        "is_dir": is_dir,
        "free_gb": free_gb,
    }


def get_path_snapshot() -> dict[str, Any]:
    """
    Return full path diagnostic snapshot.

    Used by:
        GET /api/system/paths

    Description:
        Helps user/admin verify that ComfyUI paths, model paths,
        upload input path, and workflow template path are correct
        before running real generation.
    """
    return {
        "config": {
            "config_json_path": str(CONFIG_JSON_PATH),
            "config_json_loaded": bool(_CONFIG_JSON),
            "config_json_error": CONFIG_JSON_ERROR,
        },
        "project": {
            "project_root": _dir_info(PROJECT_ROOT),
            "backend_dir": _dir_info(BACKEND_DIR),
            "outputs_dir": _dir_info(OUTPUTS_DIR),
            "project_models_dir": _dir_info(PROJECT_MODELS_DIR),
        },
        "comfyui": {
            "api_base_url": COMFYUI_API_BASE_URL,
            "request_timeout_seconds": COMFYUI_REQUEST_TIMEOUT_SECONDS,
            "websocket_timeout_seconds": COMFYUI_WEBSOCKET_TIMEOUT_SECONDS,
            "root": _dir_info(COMFYUI_ROOT),
            "app_dir": _dir_info(COMFYUI_APP_DIR),
            "input_dir": _dir_info(COMFYUI_INPUT_DIR),
            "output_dir": _dir_info(COMFYUI_OUTPUT_DIR),
            "models_dir": _dir_info(COMFYUI_MODELS_DIR),
            "diffusion_models_dir": _dir_info(COMFYUI_DIFFUSION_MODELS_DIR),
            "text_encoders_dir": _dir_info(COMFYUI_TEXT_ENCODERS_DIR),
            "vae_dir": _dir_info(COMFYUI_VAE_DIR),
            "loras_dir": _dir_info(COMFYUI_LORAS_DIR),
            "custom_nodes_dir": _dir_info(COMFYUI_CUSTOM_NODES_DIR),
        },
        "upload": {
            "max_file_size_mb": UPLOAD_MAX_FILE_SIZE_MB,
            "max_file_size_bytes": UPLOAD_MAX_FILE_SIZE_BYTES,
            "allowed_image_extensions": ALLOWED_IMAGE_EXTENSIONS,
            "allowed_video_extensions": ALLOWED_VIDEO_EXTENSIONS,
            "allowed_audio_extensions": ALLOWED_AUDIO_EXTENSIONS,
            "allowed_reference_extensions": ALLOWED_REFERENCE_EXTENSIONS,
        },
        "workflow": {
            "template_dir": _dir_info(WORKFLOW_TEMPLATE_DIR),
            "ref2va_workflow_filename": REF2VA_WORKFLOW_FILENAME,
            "ref2va_workflow_path": _file_info(REF2VA_WORKFLOW_PATH),
            "t2v_workflow_filename": T2V_WORKFLOW_FILENAME,
            "t2v_workflow_path": _file_info(T2V_WORKFLOW_PATH),
        },
        "comfyui_model_files": {
            "diffusion_model": _file_info(
                COMFYUI_DIFFUSION_MODELS_DIR / DIFFUSION_MODEL_FILENAME
            ),
            "text_encoder": _file_info(
                COMFYUI_TEXT_ENCODERS_DIR / TEXT_ENCODER_FILENAME
            ),
            "video_vae": _file_info(
                COMFYUI_VAE_DIR / VIDEO_VAE_FILENAME
            ),
            "audio_vae": _file_info(
                COMFYUI_VAE_DIR / AUDIO_VAE_FILENAME
            ),
            "lora": _file_info(
                COMFYUI_LORAS_DIR / LORA_FILENAME
            ),
            "t2v_diffusion_model": _file_info(
                COMFYUI_DIFFUSION_MODELS_DIR / T2V_DIFFUSION_MODEL_FILENAME
            ),
            "t2v_lora": _file_info(
                COMFYUI_LORAS_DIR / T2V_LORA_FILENAME
            ),
        },
        "llm": {
            "models_dir": _dir_info(LLM_MODELS_DIR),
            "model_filename": LLM_MODEL_FILENAME,
            "model_file": _file_info(LLM_MODELS_DIR / LLM_MODEL_FILENAME),
            "n_gpu_layers": LLM_N_GPU_LAYERS,
            "n_ctx": LLM_N_CTX,
            "idle_timeout_seconds": LLM_IDLE_TIMEOUT_SECONDS,
            "temperature": LLM_TEMPERATURE,
            "top_p": LLM_TOP_P,
            "repeat_penalty": LLM_REPEAT_PENALTY,
            "max_tokens": LLM_MAX_TOKENS,
        },
    }

# ========================================
# Connection: Local / RunPod Pod (remote ComfyUI)
# ========================================
from urllib.parse import urlparse as _urlparse

COMFYUI_MODE = str(_get("comfyui_mode", "auto")).strip().lower()
RUNPOD_POD_ID = str(_get("runpod_pod_id", "")).strip()
RUNPOD_PROXY_DOMAIN = str(_get("runpod_proxy_domain", "proxy.runpod.net")).strip()
RUNPOD_HTTP_PORT = _int_value("runpod_http_port", 8188)
COMFYUI_AUTH_TOKEN = str(_get("comfyui_auth_token", "")).strip()

COMFYUI_REMOTE_REQUEST_TIMEOUT_SECONDS = _float_value("comfyui_remote_request_timeout_seconds", 30.0)
COMFYUI_REMOTE_WEBSOCKET_TIMEOUT_SECONDS = _float_value("comfyui_remote_websocket_timeout_seconds", 60.0)

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def build_runpod_proxy_url(pod_id: str, port: int = 8188, domain: str = "proxy.runpod.net") -> str:
    pod_id = (pod_id or "").strip()
    if not pod_id:
        return ""
    return f"https://{pod_id}-{port}.{domain}"


def _url_is_remote(url: str) -> bool:
    try:
        host = (_urlparse(url).hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    return host not in _LOCAL_HOSTS


def compute_is_remote(mode: str, url: str) -> bool:
    mode = (mode or "auto").strip().lower()
    if mode == "local":
        return False
    if mode == "remote":
        return True
    return _url_is_remote(url)


if not str(_get("comfyui_api_base_url", "")).strip() and COMFYUI_MODE == "remote" and RUNPOD_POD_ID:
    COMFYUI_API_BASE_URL = build_runpod_proxy_url(RUNPOD_POD_ID, RUNPOD_HTTP_PORT, RUNPOD_PROXY_DOMAIN)

COMFYUI_IS_REMOTE = compute_is_remote(COMFYUI_MODE, COMFYUI_API_BASE_URL)

# ========================================
# FFmpeg configuration (สำหรับดึงเฟรม / ต่อวิดีโอ)
# ========================================

# อนุญาตให้เครื่องอื่นใน LAN เรียก /mcp ได้ (ค่าเริ่มต้น: เฉพาะ loopback) — รับ bool หรือสตริง "true"/"false"
_raw_mcp_allow_lan = _get("mcp_allow_lan", False)
MCP_ALLOW_LAN = (
    _raw_mcp_allow_lan
    if isinstance(_raw_mcp_allow_lan, bool)
    else str(_raw_mcp_allow_lan).strip().lower() in ("1", "true", "yes", "on")
)

FFMPEG_PATH = str(_get("ffmpeg_path", "")).strip()
FFMPEG_TIMEOUT_SECONDS = _float_value("ffmpeg_timeout_seconds", 60.0)
FRAMES_OUTPUT_DIR = _path_value("frames_output_dir", str(OUTPUTS_DIR / "frames"))

# Windows standard paths ที่ค้นหาอัตโนมัติ
FFMPEG_SEARCH_PATHS = [
    # Bundled ในโปรเจกต์
    str(BACKEND_DIR / "ffmpeg.exe"),
    str(BACKEND_DIR / "bin" / "ffmpeg.exe"),
    # Windows standard
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
    # Chocolatey / Scoop
    r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
    str(Path.home() / "scoop" / "shims" / "ffmpeg.exe"),
]


def get_connection_snapshot() -> dict[str, Any]:
    return {
        "mode": COMFYUI_MODE,
        "is_remote": COMFYUI_IS_REMOTE,
        "base_url": COMFYUI_API_BASE_URL,
        "runpod_pod_id": RUNPOD_POD_ID,
        "runpod_proxy_domain": RUNPOD_PROXY_DOMAIN,
        "runpod_http_port": RUNPOD_HTTP_PORT,
        "has_auth_token": bool(COMFYUI_AUTH_TOKEN),
        "request_timeout_seconds": (
            COMFYUI_REMOTE_REQUEST_TIMEOUT_SECONDS if COMFYUI_IS_REMOTE else COMFYUI_REQUEST_TIMEOUT_SECONDS
        ),
        "input_dir": str(COMFYUI_INPUT_DIR),
    }


def _persist_connection_to_config_json() -> None:
    data = dict(_CONFIG_JSON)
    data["comfyui_mode"] = COMFYUI_MODE
    data["comfyui_api_base_url"] = COMFYUI_API_BASE_URL
    data["runpod_pod_id"] = RUNPOD_POD_ID
    data["comfyui_auth_token"] = COMFYUI_AUTH_TOKEN
    try:
        with CONFIG_JSON_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _CONFIG_JSON.update(data)
    except OSError:
        pass


def apply_connection_settings(
    mode: str | None = None,
    base_url: str | None = None,
    runpod_pod_id: str | None = None,
    auth_token: str | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    global COMFYUI_MODE, COMFYUI_API_BASE_URL, RUNPOD_POD_ID, COMFYUI_AUTH_TOKEN, COMFYUI_IS_REMOTE

    if mode is not None:
        COMFYUI_MODE = str(mode).strip().lower()
    if runpod_pod_id is not None:
        RUNPOD_POD_ID = str(runpod_pod_id).strip()
    if auth_token is not None:
        COMFYUI_AUTH_TOKEN = str(auth_token).strip()

    if base_url is not None:
        # แยก "ไม่ได้ส่งมา" (None → คงค่าเดิม) ออกจาก "ส่งค่าว่าง" ("" → ล้างจริง)
        # ถ้าส่ง "" ต้องว่างจริง ห้ามฟื้นค่าเก่าจาก runpod_pod_id
        COMFYUI_API_BASE_URL = str(base_url).strip().rstrip("/")
    elif COMFYUI_MODE == "remote" and RUNPOD_POD_ID:
        COMFYUI_API_BASE_URL = build_runpod_proxy_url(RUNPOD_POD_ID, RUNPOD_HTTP_PORT, RUNPOD_PROXY_DOMAIN)
    elif COMFYUI_MODE == "local":
        COMFYUI_API_BASE_URL = "http://127.0.0.1:8188"

    COMFYUI_IS_REMOTE = compute_is_remote(COMFYUI_MODE, COMFYUI_API_BASE_URL)

    if persist:
        _persist_connection_to_config_json()

    return get_connection_snapshot()