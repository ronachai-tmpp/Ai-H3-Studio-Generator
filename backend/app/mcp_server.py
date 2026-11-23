"""MCP server (h3-studio) ให้ Claude Code สร้างและคุมซีรีย์ผ่าน tools

ลงทะเบียนเป็น route เดียว /mcp ของ FastAPI (streamable HTTP แบบ stateless + JSON) รับเฉพาะ client จาก loopback
เว้นแต่เปิด mcp_allow_lan เพราะ series_add_character อ่านไฟล์รูปตาม path บนเครื่อง backend
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from fastapi import FastAPI
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from app.services.series_export import export_series, review_images
from app.services.series_gateway import StudioGateway
from app.services.series_guide import SERIES_GUIDE, new_series_prompt
from app.services.series_models import (
    ALLOWED_DURATIONS,
    ALLOWED_MEGAPIXELS,
    DEFAULT_ASPECT_RATIO,
    DEFAULT_MEGAPIXELS,
    Series,
    SeriesError,
    progress_of,
    waiting_for,
)
from app.services.series_service import SeriesService
from app.services.series_store import SeriesStore
from app.services.workflow_service import ALLOWED_ASPECT_RATIOS

LOOPBACK_HOSTS = ("127.0.0.1", "::1")
LOOPBACK_ORIGIN_HOSTS = ("127.0.0.1", "localhost", "::1")
FORBIDDEN_MESSAGE = "MCP รับเฉพาะการเชื่อมต่อจากเครื่องนี้ (ตั้ง mcp_allow_lan เพื่อเปิด)"
FORBIDDEN_ORIGIN_MESSAGE = "MCP ไม่รับคำขอจากหน้าเว็บของเว็บไซต์อื่น (Origin ต้องเป็น localhost)"
WAIT_MIN_SECONDS = 5
WAIT_MAX_SECONDS = 300


def _minutes(seconds: float) -> str:
    return f"{seconds / 60:.1f} min"


def _clock(seconds: float | None) -> str:
    if not seconds:
        return "-"
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _overview_line(item: dict) -> str:
    extra = ""
    if item["pause_reason"]:
        extra += f" pause={item['pause_reason']}"
    if item["waiting_for"]:
        extra += f" waiting_for={item['waiting_for']}"
    done, total = item["progress"]["scenes_done"], item["progress"]["scenes_total"]
    return (f"{item['id']}  {item['status']}{extra}  \"{item['title']}\"  "
            f"EP {item['episodes_done']}/{item['episodes_total']}  scenes {done}/{total}")


def _series_block(series: Series, cursor: int) -> str:
    """สรุปซีรีส์เป็นข้อความกระชับ (ใช้ทั้ง series_status และ series_wait)"""
    head = f"{series.id}  {series.status}  \"{series.title}\""
    if series.pause_reason:
        head += f"  pause_reason={series.pause_reason}"
    if series.pause_message:
        head += f" ({series.pause_message})"
    waiting = waiting_for(series)
    if waiting:
        head += f"  waiting_for={waiting}"
    if series.story_complete:
        head += "  story_complete"
    lines = [head]

    for ep in series.episodes:
        lines.append(f"EP{ep.number:02d} {ep.status} {_clock(ep.duration)} \"{ep.title}\"")

    current = next((e for e in series.episodes if e.status != "DONE"), None)
    if current is not None:
        for sc in current.scenes:
            if sc.status == "DONE":
                continue
            line = (f"  EP{current.number:02d} scene {sc.index} {sc.mode} {sc.status} "
                    f"{sc.progress}% attempts={sc.attempts}")
            if sc.error:
                line += f" error: {sc.error}"
            lines.append(line)

    for char in series.characters:
        state = "has reference" if char.reference_images else "needs casting"
        lines.append(f"character {char.name}: {state}")

    progress = progress_of(series)
    line = f"progress: {progress['scenes_done']}/{progress['scenes_total']} scenes"
    if progress["eta_seconds"] is not None:
        line += f", ETA {_minutes(progress['eta_seconds'])}"
    lines.append(line)
    lines.append(f"event_cursor: {cursor}")
    return "\n".join(lines)


def _status_text(store: SeriesStore, series_id: str) -> str:
    with store.lock:
        return _series_block(store.get(series_id), store.cursor(series_id))


def build_mcp(service: SeriesService, store: SeriesStore, gateway: StudioGateway,
              outputs_dir: Path) -> MCPServer:
    """สร้าง MCP server พร้อม tools ทั้งหมด (ผูกกับ service/store/gateway ที่ส่งเข้ามา)"""
    server = MCPServer(
        "h3-studio",
        instructions=(
            "Drives the local H3 Studio video generator to produce vertical short-drama series. "
            "Call `series_guide` before writing a series."
        ),
    )

    @server.tool()
    def studio_status() -> str:
        """Check that ComfyUI and the queue are ready and see the allowed values and existing series. Call it before planning."""
        info = gateway.studio_info()
        vram = info.get("vram")
        vram_text = f"{vram['free']}/{vram['total']} bytes free" if vram else "unknown"
        lines = [
            f"ComfyUI: {'reachable' if info['comfyui_ok'] else 'NOT reachable'}, "
            f"mode {info['comfyui_mode']}, VRAM {vram_text}",
            f"queue: {info['queue_pending']} pending, {info['queue_running']} running",
            f"durations: {list(ALLOWED_DURATIONS)}",
            f"megapixels: {list(ALLOWED_MEGAPIXELS)}",
            f"aspect ratios: {sorted(ALLOWED_ASPECT_RATIOS)}",
        ]
        overview = service.overview()
        lines.append("series:" if overview else "series: none")
        lines += [f"  {_overview_line(item)}" for item in overview]
        if store.load_errors:
            lines.append(f"unreadable series folders: {', '.join(store.load_errors)}")
        return "\n".join(lines)

    @server.tool()
    def series_guide() -> str:
        """Read the series-writing guide (structure, scene modes, prompt layout, limits). Call it before writing a series."""
        return SERIES_GUIDE

    @server.tool()
    def series_create(title: str, logline: str = "", style_notes: str = "",
                      aspect_ratio: str = DEFAULT_ASPECT_RATIO, megapixels: float = DEFAULT_MEGAPIXELS,
                      low_vram: bool = False, run_mode: str = "autopilot") -> str:
        """Create a new series (status DRAFT) and return its id.

        megapixels must be one of 0.1, 0.25, 0.35, 0.5, 0.75, 1.0. run_mode is "autopilot"
        (runs through) or "review" (pauses after each episode). low_vram selects the GGUF models.
        """
        try:
            series = service.create_series(title, logline, style_notes, aspect_ratio, megapixels,
                                           low_vram, run_mode)
        except SeriesError as exc:
            return f"ERROR: {exc}"
        return f"created series {series.id} \"{series.title}\" (DRAFT)"

    @server.tool()
    def series_add_character(series_id: str, name: str, description: str = "",
                             image_paths: list[str] | None = None,
                             casting_prompt: str | None = None) -> str:
        """Add or update a character. Give image_paths (image files on the backend machine, or paths under outputs/) and/or a casting_prompt that makes the runner generate the reference.

        Calling it for an existing character REPLACES its description, images and casting_prompt
        (values you leave out are cleared, not kept). Passing casting_prompt without image_paths
        discards the current images and casts the character again.
        """
        try:
            character = service.set_character(series_id, name, description, image_paths, casting_prompt)
        except SeriesError as exc:
            return f"ERROR: {exc}"
        state = "has reference" if character.reference_images else "needs casting"
        return f"character {character.name}: {state} ({len(character.reference_images)} images)"

    @server.tool()
    def series_write_episode(series_id: str, title: str, scenes: list[dict], synopsis: str = "",
                             caption: str = "", hashtags: list[str] | None = None,
                             episode_number: int | None = None) -> str:
        """Append a new episode, or overwrite an episode that has not started when episode_number is given.

        Each scene dict has: prompt (str, required), mode ("text" | "ref" | "chain", required),
        beat (str, short note of what happens), characters (list of character names, needed for
        "ref"), duration_seconds (5, 8, 10, 12 or 15; default 5), seed (int, default -1 = random).
        """
        try:
            episode = service.write_episode(series_id, title, scenes, synopsis, caption, hashtags,
                                            episode_number)
        except SeriesError as exc:
            return f"ERROR: {exc}"
        return f"episode {episode.number} \"{episode.title}\" written with {len(episode.scenes)} scenes"

    @server.tool()
    def series_update_scene(series_id: str, episode: int, scene: int, prompt: str | None = None,
                            beat: str | None = None, mode: str | None = None,
                            characters: list[str] | None = None, duration_seconds: int | None = None,
                            seed: int | None = None, regenerate: bool = False) -> str:
        """Edit a scene; set regenerate=true to generate it again (following chain scenes reset too).

        mode is "text", "ref" or "chain"; duration_seconds is 5, 8, 10, 12 or 15.
        """
        try:
            reset = service.update_scene(series_id, episode, scene, prompt=prompt, beat=beat, mode=mode,
                                         characters=characters, duration_seconds=duration_seconds,
                                         seed=seed, regenerate=regenerate)
        except SeriesError as exc:
            return f"ERROR: {exc}"
        if reset:
            names = ", ".join(f"EP{e:02d}.{s}" for e, s in reset)
            return f"scene EP{episode:02d}.{scene} updated; reset to PENDING: {names}"
        return f"scene EP{episode:02d}.{scene} updated"

    @server.tool()
    def series_control(series_id: str, action: str) -> str:
        """Control a series. action is one of: start (DRAFT only), pause, resume (also after a casting/review pause), finish (declare the story complete), cancel."""
        try:
            series = service.control(series_id, action)
        except SeriesError as exc:
            return f"ERROR: {exc}"
        return f"{action} ok: {series.id} is now {series.status}"

    @server.tool()
    def series_status(series_id: str | None = None) -> str:
        """Without series_id list all series in one line each; with series_id show episodes, unfinished scenes, characters, progress and event_cursor."""
        try:
            if series_id is None:
                overview = service.overview()
                return "\n".join(_overview_line(i) for i in overview) if overview else "no series yet"
            return _status_text(store, series_id)
        except SeriesError as exc:
            return f"ERROR: {exc}"

    @server.tool()
    def series_wait(series_id: str, timeout_seconds: int = 120, after_event: int = -1) -> str:
        """Block until the next series event (scene done/failed, episode done, pause, finish) or timeout, then return the events and the status.

        timeout_seconds is clamped to 5-300. after_event is the event_cursor from an earlier
        status (-1 = only events from now on). Returns at once with the status when the series
        is not RUNNING (DRAFT, PAUSED, DONE, CANCELLED), since nothing happens until you act.
        """
        # tool แบบ sync: แพ็กเกจ mcp รันใน worker thread จึงรอ lock ของ store ได้โดยไม่บล็อก event loop
        timeout = max(WAIT_MIN_SECONDS, min(WAIT_MAX_SECONDS, timeout_seconds))
        try:
            after = store.cursor(series_id) if after_event < 0 else after_event
            if store.get(series_id).status != "RUNNING":  # ไม่มีอะไรเกิดจนกว่าจะสั่งการ: ตอบทันที
                return "events: none (series is not RUNNING)\n" + _status_text(store, series_id)
            _, events = store.wait_events(series_id, after, float(timeout))
            lines = [f"events: {', '.join(events)}" if events else "events: none (timeout)"]
            lines.append(_status_text(store, series_id))
        except SeriesError as exc:
            return f"ERROR: {exc}"
        return "\n".join(lines)

    @server.tool()
    def series_review(series_id: str, episode: int | None = None, scene: int | None = None,
                      character: str | None = None, frames: int = 4) -> list:
        """Look at images. Give character for its reference images; episode+scene for sampled frames (frames = 1-8, default 4) and the prompt; episode alone for the last frame of every finished scene."""
        try:
            text, paths = review_images(store, gateway, series_id, episode=episode, scene=scene,
                                        character=character, frames=frames)
        except SeriesError as exc:
            return [f"ERROR: {exc}"]
        return [text, *[Image(path=outputs_dir / p) for p in paths]]

    @server.tool()
    def series_export(series_id: str) -> str:
        """Copy the finished episodes to outputs/series/<id>/export/ with readable names, covers and manifest.json."""
        try:
            result = export_series(store, outputs_dir, series_id)
        except SeriesError as exc:
            return f"ERROR: {exc}"
        return f"exported to outputs/{result['dir']}: " + ", ".join(result["files"])

    @server.prompt()
    def new_series(idea: str) -> str:
        """Plan and produce a whole series from an idea."""
        return new_series_prompt(idea)

    return server


class McpGuard:
    """ASGI wrapper ของ /mcp

    - ทุกโหมด: ปฏิเสธคำขอที่มี Origin ไม่ใช่ localhost (กันหน้าเว็บอื่นยิงเข้ามาผ่านเบราว์เซอร์) —
      client ของ MCP อย่าง Claude Code ไม่ส่ง Origin จึงผ่าน
    - allow_lan เป็น false: รับเฉพาะ client IP แบบ loopback
    """

    def __init__(self, app: ASGIApp, allow_lan: bool):
        self.app = app
        self.allow_lan = allow_lan

    @staticmethod
    def _origin_allowed(scope: Scope) -> bool:
        for key, value in scope.get("headers", []):
            if key == b"origin":
                try:
                    host = urlsplit(value.decode("latin-1")).hostname
                except ValueError:
                    return False
                return host in LOOPBACK_ORIGIN_HOSTS
        return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            client = scope.get("client")
            if not self.allow_lan and (client is None or client[0] not in LOOPBACK_HOSTS):
                response = JSONResponse({"detail": FORBIDDEN_MESSAGE}, status_code=403)
                await response(scope, receive, send)
                return
            if not self._origin_allowed(scope):
                response = JSONResponse({"detail": FORBIDDEN_ORIGIN_MESSAGE}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def mcp_asgi_app(server: MCPServer, allow_lan: bool) -> ASGIApp:
    """ASGI app ของ streamable HTTP ที่ path /mcp (เรียกได้ครั้งเดียวต่อ server เพราะสร้าง session_manager)

    ค่าเริ่มต้น: ป้องกัน DNS rebinding ของแพ็กเกจ (Host ต้องเป็น localhost/127.0.0.1)
    allow_lan: ปิดการเช็ก Host ของแพ็กเกจเพราะเครื่องอื่นเรียกด้วย IP ของ LAN
    การเช็ก Origin และ client IP ทำใน McpGuard เสมอ ไม่ขึ้นกับค่าของแพ็กเกจ
    """
    kwargs: dict = {}
    if allow_lan:
        kwargs["transport_security"] = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    app = server.streamable_http_app(
        streamable_http_path="/mcp", json_response=True, stateless_http=True, **kwargs,
    )
    return McpGuard(app, allow_lan)


def register_mcp(app: FastAPI, mcp_app: ASGIApp) -> None:
    """ลงทะเบียนเฉพาะ path /mcp (ไม่ใช้ Mount("/") เพราะจะดัก path อื่นทั้งหมด ทำให้ redirect ท้าย / และ 405 หาย)"""
    app.router.routes.append(Route("/mcp", endpoint=mcp_app, include_in_schema=False))
