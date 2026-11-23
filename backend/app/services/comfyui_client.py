"""
========================================
ComfyUI Client (v5 - Dynamic Progress + Cache Guard)
========================================
Description:
    Client สำหรับสื่อสารกับ ComfyUI API
    - submit workflow ผ่าน POST /prompt
    - ติดตาม progress ผ่าน WebSocket /ws
    - ดึง history ผ่าน GET /history/{prompt_id}
    - ดาวน์โหลด output ผ่าน GET /view

v5 changes:
    - เพิ่ม main_sampler_id + saw_main_sampler flag
    - เพิ่ม guard: node ที่มาจาก execution_cached และเป็นช่วงสูง (>=90%)
      จะไม่ทำให้ progress กระโดด จนกว่า main sampler จะเริ่มรันจริง
    - แก้ปัญหา progress เด้ง 97% ตั้งแต่กด gen
    - ถ้าไม่ส่ง main_sampler_id มา guard จะปิดตัวเอง (ไม่กระทบ flow เดิม)
    - ไม่ใช้ global state เพื่อความปลอดภัยกรณี queue ทำงานหลายงาน
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

import websockets

from app.core import config


class ComfyUIError(RuntimeError):
    pass


VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}


# ========================================
# HTTP helpers
# ========================================

def _http_request(
    method: str,
    path: str,
    payload: Any | None = None,
    timeout: float | None = None,
    binary: bool = False,
) -> Any:
    url = f"{config.COMFYUI_API_BASE_URL}{path}"
    data = None
    headers = {
        "Accept": "application/octet-stream" if binary else "application/json",
        "User-Agent": "MiniMax-H3-Studio-Backend/0.1",
    }

    if config.COMFYUI_AUTH_TOKEN:
        headers["Authorization"] = f"Bearer {config.COMFYUI_AUTH_TOKEN}"

    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)

    default_timeout = (
        config.COMFYUI_REMOTE_REQUEST_TIMEOUT_SECONDS
        if config.COMFYUI_IS_REMOTE
        else config.COMFYUI_REQUEST_TIMEOUT_SECONDS
    )
    request_timeout = timeout or default_timeout

    try:
        with urllib.request.urlopen(request, timeout=request_timeout) as response:
            raw = response.read()
            if binary:
                return raw, response.headers.get("Content-Type", "application/octet-stream")
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ComfyUIError(f"ComfyUI HTTP {exc.code} ที่ {path}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ComfyUIError(f"เชื่อมต่อ ComfyUI ไม่สำเร็จที่ {url}: {exc.reason}") from exc


def get_system_stats() -> dict[str, Any]:
    return _http_request("GET", "/system_stats")


# ========================================
# Prompt submit
# ========================================

def _clean_workflow_for_prompt(workflow: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}

    for node_id, node in workflow.items():
        if isinstance(node, dict):
            cleaned[node_id] = {k: v for k, v in node.items() if k != "_meta"}
        else:
            cleaned[node_id] = node

    return cleaned


def submit_prompt(workflow: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    client_id = uuid.uuid4().hex
    clean_workflow = _clean_workflow_for_prompt(workflow)
    payload = {"prompt": clean_workflow, "client_id": client_id}
    response = _http_request("POST", "/prompt", payload=payload, timeout=30.0)

    prompt_id = response.get("prompt_id")
    if not prompt_id:
        raise ComfyUIError(
            f"ComfyUI /prompt ไม่คืน prompt_id: {json.dumps(response, ensure_ascii=False)}"
        )

    node_errors = response.get("node_errors")
    if node_errors:
        raise ComfyUIError(
            "ComfyUI มี node_errors ก่อนเริ่มรัน: "
            + json.dumps(node_errors, ensure_ascii=False)
        )

    return str(prompt_id), client_id, response


# ========================================
# History
# ========================================

def get_history(prompt_id: str) -> dict[str, Any]:
    try:
        return _http_request("GET", f"/history/{prompt_id}", timeout=15.0)
    except ComfyUIError as exc:
        if "HTTP 404" in str(exc):
            return {}
        raise


def wait_for_history(prompt_id: str, timeout: float = 1800.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_history: dict[str, Any] = {}

    while time.monotonic() < deadline:
        try:
            history = get_history(prompt_id)
        except OSError as exc:
            # ComfyUI ตอบช้าชั่วคราวระหว่างเรนเดอร์หนัก (socket timeout / connection reset)
            # งานยังรันอยู่ฝั่ง ComfyUI: รอแล้วถามใหม่จนกว่าจะถึง deadline
            print(f"[comfyui_client] history poll ช้า/หลุดชั่วคราว prompt_id={prompt_id}: {exc}")
            time.sleep(2.0)
            continue
        last_history = history
        entry = history.get(prompt_id)

        if entry:
            status = entry.get("status") or {}
            status_str = status.get("status_str")

            if status_str == "error":
                raise ComfyUIError(
                    "ComfyUI execution error จาก history: "
                    + json.dumps(status, ensure_ascii=False)
                )

            if entry.get("outputs"):
                return entry

        time.sleep(0.5)

    raise ComfyUIError(
        f"ไม่พบ history/output ของ prompt_id={prompt_id} ภายใน {timeout} วินาที: "
        + json.dumps(last_history, ensure_ascii=False)
    )


# ========================================
# WebSocket progress tracking (v5)
# ========================================

def _build_websocket_url(client_id: str) -> str:
    base = config.COMFYUI_API_BASE_URL

    if base.startswith("https://"):
        ws_base = base.replace("https://", "wss://", 1)
    elif base.startswith("http://"):
        ws_base = base.replace("http://", "ws://", 1)
    else:
        ws_base = base

    return f"{ws_base}/ws?clientId={client_id}"


# SaveVideo candidates สำหรับ fallback
NODE_SAVE_VIDEO_CANDIDATES = ("172", "204", "92")

# Default progress ranges ครอบคลุมทั้ง REF2VA และ T2V
DEFAULT_NODE_PROGRESS_RANGES: dict[str, tuple[int, int]] = {
    # REF2VA main
    "136": (5, 35),
    "125": (35, 90),
    "122": (90, 95),
    "121": (95, 97),
    "152": (97, 98),

    # T2V main
    "162": (5, 35),
    "156": (35, 90),
    "154": (90, 95),
    "153": (95, 97),
    "161": (97, 98),

    # SaveVideo terminals
    "172": (99, 99),
    "204": (99, 99),
    "92": (98, 99),
}

# Default loading nodes
DEFAULT_LOADING_NODES = {
    # REF2VA
    "115", "119", "120", "123", "127", "128", "129",
    "131", "132", "138", "145", "147", "149", "150",

    # T2V
    "151", "152", "155", "158", "159", "160",
    "163", "164", "165", "166", "167", "168", "169", "170",
}

# Default node messages ครอบคลุมทั้ง REF2VA และ T2V
DEFAULT_NODE_MESSAGES: dict[str, str] = {
    # REF2VA
    "136": "ComfyUI กำลัง encode reference/prompt",
    "125": "ComfyUI กำลัง sampling",
    "122": "ComfyUI กำลัง decode video VAE",
    "121": "ComfyUI กำลัง decode audio VAE",
    "152": "ComfyUI กำลังประกอบวิดีโอ",

    # T2V
    "162": "ComfyUI กำลัง encode prompt",
    "156": "ComfyUI กำลัง sampling",
    "154": "ComfyUI กำลัง decode video VAE",
    "153": "ComfyUI กำลัง decode audio VAE",
    "161": "ComfyUI กำลังประกอบวิดีโอ",

    # SaveVideo
    "172": "ComfyUI กำลังบันทึกวิดีโอ",
    "204": "ComfyUI กำลังบันทึกวิดีโอ",
    "92": "ComfyUI กำลังบันทึกวิดีโอ",
}


ProgressCallback = Callable[[dict[str, Any]], None]


class _ProgressTracker:
    def __init__(
        self,
        callback: Optional[ProgressCallback],
        upscale_node_ids: Optional[set[str]] = None,
        progress_map: Optional[dict[str, tuple[int, int]]] = None,
        terminal_save_node_id: Optional[str] = None,
        node_messages: Optional[dict[str, str]] = None,
        main_sampler_id: Optional[str] = None,
    ) -> None:
        self.callback = callback
        self.upscale_node_ids = set(upscale_node_ids or set())
        self.progress_map = dict(progress_map or {})
        self.terminal_save_node_id = terminal_save_node_id
        self.node_messages = dict(node_messages or {})
        self.main_sampler_id = main_sampler_id

        self.percent = 0
        self.last_node: Optional[str] = None
        self.last_message: str = ""
        self.has_seen_real_node = False
        self.saw_terminal_node = False
        self.completed_nodes: set[str] = set()

        # ถ้าไม่ระบุ main_sampler_id → ปิด guard ( coi ว่าเห็น sampler แล้ว )
        # เพื่อไม่ให้กระทบ flow เก่าที่ไม่ได้ส่งค่านี้มา
        self.saw_main_sampler = main_sampler_id is None

    def _clamp_percent(self, value: int) -> int:
        return max(0, min(99, value))

    def _is_upscale_node(self, node_id: Optional[str]) -> bool:
        if node_id is None:
            return False

        if node_id in self.upscale_node_ids:
            return True

        # รองรับรูปแบบ flatten subgraph เก่า เช่น 205:2, 205:4
        if node_id.startswith("205:"):
            return True

        return False

    def _get_range(self, node_id: Optional[str]) -> Optional[tuple[int, int]]:
        if node_id is None:
            return None

        if node_id in self.progress_map:
            return self.progress_map[node_id]

        return DEFAULT_NODE_PROGRESS_RANGES.get(node_id)

    def _is_high_stage_node(self, node_id: Optional[str]) -> bool:
        """
        ตรวจว่า node นี้อยู่ช่วง progress สูง (>=90%) หรือไม่

        Description:
            ใช้สำหรับ guard execution_cached
            ไม่ให้ node ช่วงท้าย (decode/create/save) ที่ถูก cache
            ทำให้ progress กระโดดก่อน main sampler เริ่มรันจริง
        """
        if node_id is None:
            return False

        rng = self._get_range(node_id)
        if rng is None:
            return False

        return rng[0] >= 90

    def _is_terminal_save_node(self, node_id: Optional[str]) -> bool:
        if node_id is None:
            return False

        if self.terminal_save_node_id is not None and node_id == self.terminal_save_node_id:
            return True

        return node_id in NODE_SAVE_VIDEO_CANDIDATES

    def _percent_for_node(
        self,
        node_id: Optional[str],
        ratio: Optional[float] = None,
        completed: bool = False,
    ) -> int:
        if node_id is None:
            if self.saw_terminal_node:
                return 99
            return self.percent

        self.has_seen_real_node = True

        # Terminal SaveVideo node
        if self._is_terminal_save_node(node_id):
            self.saw_terminal_node = True
            node_range = self._get_range(node_id) or (99, 99)
            start, end = node_range

            if completed:
                return self._clamp_percent(end)

            if ratio is None:
                return self._clamp_percent(start)

            ratio = max(0.0, min(1.0, float(ratio)))
            return self._clamp_percent(int(start + ((end - start) * ratio)))

        # Upscale compute nodes
        if self._is_upscale_node(node_id):
            start, end = (98, 99)

            if completed:
                return self._clamp_percent(end)

            if ratio is None:
                return self._clamp_percent(start)

            ratio = max(0.0, min(1.0, float(ratio)))
            return self._clamp_percent(int(start + ((end - start) * ratio)))

        # Main pipeline nodes
        node_range = self._get_range(node_id)

        if node_range is not None:
            start, end = node_range

            if completed:
                return self._clamp_percent(end)

            if ratio is None:
                return self._clamp_percent(start)

            ratio = max(0.0, min(1.0, float(ratio)))
            return self._clamp_percent(int(start + ((end - start) * ratio)))

        # Loading nodes
        if node_id in DEFAULT_LOADING_NODES:
            if completed:
                return self._clamp_percent(max(self.percent, 4))
            return self._clamp_percent(max(self.percent, 2))

        # Unknown node with ratio: ค่อย ๆ ขยับเล็กน้อย
        if ratio is not None and self.percent < 35:
            return self._clamp_percent(self.percent + 1)

        return self._clamp_percent(self.percent)

    def _message_for_node(
        self,
        msg_type: str,
        node_id: Optional[str],
        value: Optional[int] = None,
        max_value: Optional[int] = None,
    ) -> str:
        if node_id is None:
            if self.saw_terminal_node:
                return "ComfyUI กำลังสรุปผลงาน"
            return "ComfyUI กำลังเตรียมงาน"

        # Dynamic messages ก่อน
        if node_id in self.node_messages:
            base = self.node_messages[node_id]

            if value is not None and max_value is not None:
                return f"{base} ({value}/{max_value})"

            return base

        # Default messages
        if node_id in DEFAULT_NODE_MESSAGES:
            base = DEFAULT_NODE_MESSAGES[node_id]

            if value is not None and max_value is not None:
                return f"{base} ({value}/{max_value})"

            return base

        # Upscale nodes
        if self._is_upscale_node(node_id):
            if value is not None and max_value is not None:
                return f"ComfyUI กำลัง upscale วิดีโอ ({value}/{max_value})"
            return "ComfyUI กำลัง upscale วิดีโอ"

        # Terminal save
        if self._is_terminal_save_node(node_id):
            return "ComfyUI กำลังบันทึกวิดีโอ"

        # Loading nodes
        if node_id in DEFAULT_LOADING_NODES:
            return f"ComfyUI กำลังเตรียม node {node_id}"

        return f"ComfyUI กำลังประมวลผล node {node_id}"

    def emit(
        self,
        msg_type: str,
        node_id: Optional[str],
        value: Optional[int] = None,
        max_value: Optional[int] = None,
        ratio: Optional[float] = None,
        completed: bool = False,
        force: bool = False,
        from_cache: bool = False,
    ) -> None:
        new_percent = self._percent_for_node(
            node_id=node_id,
            ratio=ratio,
            completed=completed,
        )

        # Guard: ถ้า node มาจาก cache และเป็นช่วงสูง (>=90%)
        # แต่ยังไม่มี main sampler เริ่มรัน → อย่ากระโดด percent
        # กัน progress เด้ง 97/98% ตั้งแต่ต้น ทั้งที่ยังไม่ sampling
        if (
            from_cache
            and self._is_high_stage_node(node_id)
            and not self.saw_main_sampler
        ):
            new_percent = self.percent

        message = self._message_for_node(
            msg_type=msg_type,
            node_id=node_id,
            value=value,
            max_value=max_value,
        )

        changed_percent = new_percent > self.percent
        changed_message = message != self.last_message
        changed_node = node_id != self.last_node

        if changed_percent:
            self.percent = new_percent

        if not (changed_percent or changed_message or changed_node or force):
            return

        self.last_node = node_id
        self.last_message = message

        if self.callback is not None:
            self.callback({
                "percent": self.percent,
                "node": node_id,
                "message": message,
                "value": value,
                "max": max_value,
                "type": msg_type,
            })


def _safe_json_message(raw: Any) -> Optional[dict[str, Any]]:
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")

        if isinstance(raw, str):
            parsed = json.loads(raw)
        else:
            parsed = raw

        if isinstance(parsed, dict):
            return parsed

        if isinstance(parsed, (list, tuple)) and len(parsed) >= 2:
            return {"type": parsed[0], "data": parsed[1]}

        return None
    except Exception:
        return None


def _log_ws_message(msg_type: str, data: dict[str, Any]) -> None:
    node = data.get("node")
    value = data.get("value")
    max_value = data.get("max")
    prompt_id = data.get("prompt_id")

    if msg_type == "progress_preview":
        print(f"[comfyui_ws] type={msg_type} node={node} prompt_id={prompt_id}")
        return

    print(
        "[comfyui_ws] "
        f"type={msg_type} node={node} value={value} max={max_value} prompt_id={prompt_id}"
    )


async def _wait_for_completion_async(
    prompt_id: str,
    client_id: str,
    progress_callback: Optional[ProgressCallback],
    timeout: float,
    upscale_node_ids: Optional[set[str]] = None,
    progress_map: Optional[dict[str, tuple[int, int]]] = None,
    terminal_save_node_id: Optional[str] = None,
    node_messages: Optional[dict[str, str]] = None,
    main_sampler_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    ws_url = _build_websocket_url(client_id)
    deadline = time.monotonic() + timeout if timeout > 0 else None

    tracker = _ProgressTracker(
        callback=progress_callback,
        upscale_node_ids=upscale_node_ids,
        progress_map=progress_map,
        terminal_save_node_id=terminal_save_node_id,
        node_messages=node_messages,
        main_sampler_id=main_sampler_id,
    )

    tracker.emit(msg_type="startup", node_id=None, force=True)

    # ===== Auth header สำหรับ WebSocket (remote/RunPod ที่ต้องยืนยันตัวตน) =====
    ws_headers = {}
    if config.COMFYUI_AUTH_TOKEN:
        ws_headers["Authorization"] = f"Bearer {config.COMFYUI_AUTH_TOKEN}"

    connect_kwargs: dict[str, Any] = dict(
        ping_interval=20,
        close_timeout=5,
        max_size=None,
    )

    if ws_headers:
        # websockets คนละเวอร์ชันใช้ชื่อพารามิเตอร์ต่างกัน
        import inspect

        params = inspect.signature(websockets.connect).parameters
        if "additional_headers" in params:
            connect_kwargs["additional_headers"] = ws_headers
        elif "extra_headers" in params:
            connect_kwargs["extra_headers"] = ws_headers

    async with websockets.connect(ws_url, **connect_kwargs) as websocket:
        while True:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"รอ ComfyUI completion เกิน {timeout} วินาที")
            else:
                remaining = None

            raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
            message = _safe_json_message(raw)

            if message is None:
                continue

            msg_type = str(message.get("type", ""))
            data = message.get("data") or {}

            if not isinstance(data, dict):
                data = {}

            message_prompt_id = data.get("prompt_id")
            if message_prompt_id and message_prompt_id != prompt_id:
                continue

            _log_ws_message(msg_type, data)

            node = data.get("node")
            if node is not None:
                node = str(node)

            value = data.get("value")
            max_value = data.get("max")

            try:
                value_int = int(value) if value is not None else None
            except Exception:
                value_int = None

            try:
                max_value_int = int(max_value) if max_value is not None else None
            except Exception:
                max_value_int = None

            ratio: Optional[float] = None
            if value_int is not None and max_value_int not in (None, 0):
                ratio = float(value_int) / float(max_value_int)

            if msg_type == "execution_start":
                tracker.emit(msg_type=msg_type, node_id=None, force=True)

            elif msg_type == "execution_cached":
                nodes = data.get("nodes") or []
                for cached_node in nodes:
                    tracker.emit(
                        msg_type=msg_type,
                        node_id=str(cached_node),
                        completed=True,
                        from_cache=True,
                    )

            elif msg_type == "progress":
                # เห็น progress จาก main sampler = sampler เริ่มรันจริงแล้ว
                if node is not None and node == tracker.main_sampler_id:
                    tracker.saw_main_sampler = True

                tracker.emit(
                    msg_type=msg_type,
                    node_id=node,
                    value=value_int,
                    max_value=max_value_int,
                    ratio=ratio,
                )

            elif msg_type == "progress_preview":
                tracker.emit(
                    msg_type=msg_type,
                    node_id=node,
                    value=value_int,
                    max_value=max_value_int,
                    ratio=ratio,
                )

            elif msg_type == "executing":
                # เห็น main sampler เริ่ม execute = ปลด guard ได้
                if node is not None and node == tracker.main_sampler_id:
                    tracker.saw_main_sampler = True

                if node is None:
                    if tracker.saw_terminal_node:
                        tracker.emit(
                            msg_type=msg_type,
                            node_id=None,
                            completed=True,
                            force=True,
                        )
                        return None
                    else:
                        tracker.emit(msg_type=msg_type, node_id=None, force=True)
                        continue

                tracker.emit(
                    msg_type=msg_type,
                    node_id=node,
                    value=value_int,
                    max_value=max_value_int,
                    ratio=ratio,
                )

            elif msg_type == "executed":
                if node is not None:
                    tracker.completed_nodes.add(node)

                tracker.emit(
                    msg_type=msg_type,
                    node_id=node,
                    value=value_int,
                    max_value=max_value_int,
                    ratio=ratio,
                    completed=True,
                )

            elif msg_type == "execution_success":
                tracker.emit(
                    msg_type=msg_type,
                    node_id=None,
                    completed=True,
                    force=True,
                )
                return data.get("output")

            elif msg_type == "execution_error":
                raise ComfyUIError(
                    "ComfyUI execution error: " + json.dumps(data, ensure_ascii=False)
                )

            elif msg_type == "execution_interrupted":
                raise ComfyUIError(
                    "ComfyUI execution interrupted: " + json.dumps(data, ensure_ascii=False)
                )

            elif msg_type == "cache_hit":
                tracker.emit(
                    msg_type=msg_type,
                    node_id=node,
                    value=value_int,
                    max_value=max_value_int,
                    ratio=ratio,
                    completed=True,
                    from_cache=True,
                )

            else:
                tracker.emit(
                    msg_type=msg_type,
                    node_id=node,
                    value=value_int,
                    max_value=max_value_int,
                    ratio=ratio,
                )


def wait_for_completion(
    prompt_id: str,
    client_id: str,
    progress_callback: Optional[ProgressCallback] = None,
    timeout: float = 1800.0,
    upscale_node_ids: Optional[set[str]] = None,
    progress_map: Optional[dict[str, tuple[int, int]]] = None,
    terminal_save_node_id: Optional[str] = None,
    node_messages: Optional[dict[str, str]] = None,
    main_sampler_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    return asyncio.run(
        _wait_for_completion_async(
            prompt_id=prompt_id,
            client_id=client_id,
            progress_callback=progress_callback,
            timeout=timeout,
            upscale_node_ids=upscale_node_ids,
            progress_map=progress_map,
            terminal_save_node_id=terminal_save_node_id,
            node_messages=node_messages,
            main_sampler_id=main_sampler_id,
        )
    )


# ========================================
# Output files
# ========================================

def extract_output_files(history_entry: dict[str, Any]) -> list[dict[str, Any]]:
    outputs = history_entry.get("outputs") or {}
    files: list[dict[str, Any]] = []

    for node_id, node_output in outputs.items():
        if not isinstance(node_output, dict):
            continue

        for key, value in node_output.items():
            if not isinstance(value, list):
                continue

            for item in value:
                if not isinstance(item, dict):
                    continue

                filename = item.get("filename")
                if not filename:
                    continue

                files.append({
                    "node_id": node_id,
                    "key": key,
                    "filename": filename,
                    "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output"),
                })

    return files


def choose_video_file(files: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    videos = [
        item for item in files
        if Path(str(item.get("filename", ""))).suffix.lower() in VIDEO_EXTENSIONS
    ]

    if not videos:
        return None

    preferred = [
        item for item in videos
        if "video" in str(item.get("key", "")).lower()
    ]

    if preferred:
        return preferred[0]

    return videos[0]


def download_output_file(
    file_info: dict[str, Any],
    destination: Path,
    timeout: float = 120.0,
) -> str:
    params = urllib.parse.urlencode({
        "filename": file_info.get("filename", ""),
        "subfolder": file_info.get("subfolder", ""),
        "type": file_info.get("type", "output"),
    })

    data, content_type = _http_request(
        "GET",
        f"/view?{params}",
        timeout=timeout,
        binary=True,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)

    return content_type

# ========================================
# Remote upload (RunPod Pod / remote ComfyUI)
# ========================================

def is_remote() -> bool:
    return bool(config.COMFYUI_IS_REMOTE)


_UPLOAD_ENDPOINT_CANDIDATES = ("/upload/image", "/api/upload/image")
_UPLOAD_ENDPOINT_WORKING: Optional[str] = None


def upload_image_bytes(
    filename: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    overwrite: bool = True,
) -> dict[str, Any]:
    """
    อัปโหลดไฟล์เข้า ComfyUI input ผ่าน multipart POST

    Description:
        ComfyUI ต่างเวอร์ชัน/ต่าง proxy ใช้ path ไม่เหมือนกัน
        จึงลอง /upload/image และ /api/upload/image ตามลำดับ
        แล้วจำ path ที่ใช้ได้ไว้ใช้ครั้งต่อไป (เร็วขึ้น)
    """
    global _UPLOAD_ENDPOINT_WORKING

    boundary = f"----H3Studio{uuid.uuid4().hex}"

    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'.encode(),
        f"Content-Type: {content_type}\r\n\r\n".encode(),
        data,
        b"\r\n",
        f"--{boundary}\r\n".encode(),
        b'Content-Disposition: form-data; name="overwrite"\r\n\r\n',
        b"true" if overwrite else b"false",
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])

    candidates: list[str] = []
    if _UPLOAD_ENDPOINT_WORKING:
        candidates.append(_UPLOAD_ENDPOINT_WORKING)
    for path in _UPLOAD_ENDPOINT_CANDIDATES:
        if path not in candidates:
            candidates.append(path)

    timeout = max(
        config.COMFYUI_REMOTE_REQUEST_TIMEOUT_SECONDS
        if config.COMFYUI_IS_REMOTE
        else config.COMFYUI_REQUEST_TIMEOUT_SECONDS,
        60.0,
    )

    not_found: list[str] = []

    for path in candidates:
        url = f"{config.COMFYUI_API_BASE_URL}{path}"
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
            "User-Agent": "MiniMax-H3-Studio-Backend/0.1",
        }
        if config.COMFYUI_AUTH_TOKEN:
            headers["Authorization"] = f"Bearer {config.COMFYUI_AUTH_TOKEN}"

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                parsed = json.loads(resp.read().decode("utf-8"))

            if _UPLOAD_ENDPOINT_WORKING != path:
                print(f"[comfyui] upload endpoint ที่ใช้ได้: {path}")
                _UPLOAD_ENDPOINT_WORKING = path

            return parsed

        except urllib.error.HTTPError as exc:
            txt = exc.read().decode("utf-8", errors="replace")

            if exc.code == 404:
                not_found.append(f"{path} → 404")
                continue

            raise ComfyUIError(
                f"ComfyUI {path} HTTP {exc.code}: {txt}"
            ) from exc

        except urllib.error.URLError as exc:
            raise ComfyUIError(
                f"อัปโหลดไป ComfyUI ไม่สำเร็จที่ {url}: {exc.reason}"
            ) from exc

    raise ComfyUIError(
        "ไม่พบ endpoint อัปโหลดรูปบน ComfyUI นี้ — ลองแล้ว: "
        + ", ".join(not_found)
        + " (ตรวจว่า URL ชี้ถูกพอร์ต และ ComfyUI บน pod รันอยู่)"
    )

# ========================================
# Cancel helpers (หยุดงานฝั่ง ComfyUI จริง)
# ========================================

def interrupt_comfyui(prompt_id: Optional[str] = None) -> bool:
    """
    ส่ง POST /interrupt ไปยัง ComfyUI เพื่อหยุดงานที่กำลัง execute อยู่

    Note:
        Studio ส่งงานเข้า ComfyUI แบบ serial (ทีละ 1 งาน)
        ดังนั้น /interrupt จะหยุดเฉพาะงานของเราเอง ปลอดภัยที่จะเรียก
    """
    try:
        _http_request("POST", "/interrupt", payload={}, timeout=10.0)
        print(f"[comfyui] ส่ง interrupt แล้ว (prompt_id={prompt_id})")
        return True
    except ComfyUIError as exc:
        print(f"[comfyui] interrupt ไม่สำเร็จ: {exc}")
        return False


def delete_prompt_from_queue(prompt_id: str) -> bool:
    """
    ลบ prompt ออกจากคิวภายในของ ComfyUI
    (ใช้กรณีงานถูกส่งไปแล้วแต่ยังไม่ได้เริ่มรัน)
    """
    try:
        _http_request(
            "POST",
            "/queue",
            payload={"delete": [prompt_id]},
            timeout=10.0,
        )
        print(f"[comfyui] ลบ prompt ออกจากคิวแล้ว: {prompt_id}")
        return True
    except ComfyUIError as exc:
        print(f"[comfyui] ลบ prompt จากคิวไม่สำเร็จ: {exc}")
        return False


# ========================================
# History helper (สำหรับงานที่คืน text ไม่ใช่ไฟล์)
# ========================================

def get_history_entry(prompt_id: str) -> Optional[dict[str, Any]]:
    """
    ดึง history entry ของ prompt ถ้ายังรันไม่เสร็จจะคืน None
    (ComfyUI จะใส่ entry ลง /history เมื่อ execute จบแล้ว)
    """
    try:
        data = _http_request("GET", f"/history/{prompt_id}", timeout=30.0)
    except ComfyUIError:
        return None

    if isinstance(data, dict):
        entry = data.get(prompt_id)
        if isinstance(entry, dict) and entry:
            return entry

    return None