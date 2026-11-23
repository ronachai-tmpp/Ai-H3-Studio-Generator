from __future__ import annotations

import threading
import time
from contextlib import asynccontextmanager

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.mcp_server import build_mcp, mcp_asgi_app, register_mcp
from app.services.series_guide import SERIES_GUIDE, new_series_prompt

EXPECTED_TOOLS = {"studio_status", "series_guide", "series_create", "series_add_character",
                  "series_write_episode", "series_update_scene", "series_control", "series_status",
                  "series_wait", "series_review", "series_export"}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def make_client(service, store, gateway, outputs, allow_lan=False, client=("127.0.0.1", 50000)):
    server = build_mcp(service, store, gateway, outputs)
    asgi = mcp_asgi_app(server, allow_lan=allow_lan)

    @asynccontextmanager
    async def lifespan(app):
        async with server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/")
    def root():
        return {"ok": True}

    router = APIRouter()

    @router.get("/")
    def listing():
        return []

    app.include_router(router, prefix="/api/things")
    register_mcp(app, asgi)
    # base_url ชี้ 127.0.0.1 เพราะ server เปิดการป้องกัน DNS rebinding (Host ต้องเป็น loopback)
    return TestClient(app, base_url="http://127.0.0.1:8000", client=client)


def rpc(c, method, params=None, id_=1):
    r = c.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}})
    assert r.status_code == 200, r.text
    return r.json()["result"]


def call(c, name, **arguments):
    return rpc(c, "tools/call", {"name": name, "arguments": arguments})


@pytest.fixture
def mcp(service, store, gateway, outputs):
    with make_client(service, store, gateway, outputs) as c:
        rpc(c, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "pytest", "version": "0"}})
        yield c


def test_tools_and_prompt_are_listed(mcp):
    assert {t["name"] for t in rpc(mcp, "tools/list")["tools"]} == EXPECTED_TOOLS
    assert [p["name"] for p in rpc(mcp, "prompts/list")["prompts"]] == ["new_series"]


def test_existing_routes_keep_priority(mcp):
    assert mcp.get("/").json() == {"ok": True}


def test_create_write_start_status_roundtrip(mcp, store):
    text = call(mcp, "series_create", title="Love Story")["content"][0]["text"]
    series_id = store.list()[0].id
    assert series_id in text
    call(mcp, "series_write_episode", series_id=series_id, title="one",
         scenes=[{"prompt": "a street at night", "mode": "text", "duration_seconds": 8}])
    call(mcp, "series_control", series_id=series_id, action="start")
    status = call(mcp, "series_status", series_id=series_id)["content"][0]["text"]
    assert "RUNNING" in status and "event_cursor" in status


def test_series_error_is_returned_as_text(mcp):
    out = call(mcp, "series_status", series_id="nope")
    assert out["content"][0]["text"].startswith("ERROR: ")


def test_review_returns_images(mcp, done_series):
    content = call(mcp, "series_review", series_id=done_series.id, episode=1, scene=1, frames=2)["content"]
    assert [c["type"] for c in content] == ["text", "image", "image"]


def test_wait_returns_at_timeout_with_status(mcp, running):
    t = time.monotonic()
    text = call(mcp, "series_wait", series_id=running.id, timeout_seconds=5)["content"][0]["text"]
    assert time.monotonic() - t < 15 and running.id in text


def test_guide_and_prompt_have_the_essentials():
    for needle in ("continuing the same motion, ", "integrated_multimodal_description", "<Picture",
                   "cliffhanger", "9:16", "series_review"):
        assert needle in SERIES_GUIDE
    assert "time-travel romance" in new_series_prompt("time-travel romance")


def test_non_loopback_client_is_rejected(service, store, gateway, outputs):
    with make_client(service, store, gateway, outputs, client=("192.168.1.50", 50000)) as c:
        r = c.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 403


def test_lan_client_allowed_when_enabled(service, store, gateway, outputs):
    with make_client(service, store, gateway, outputs, allow_lan=True, client=("192.168.1.50", 50000)) as c:
        r = c.post("/mcp", headers={**HEADERS, "Host": "192.168.1.5:8000"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 200


def test_slashless_path_still_redirects(mcp):
    assert mcp.get("/api/things", follow_redirects=False).status_code == 307


def test_wrong_method_on_existing_route_is_405(mcp):
    assert mcp.delete("/", follow_redirects=False).status_code == 405


def test_unknown_path_from_lan_client_is_404_not_403(service, store, gateway, outputs):
    with make_client(service, store, gateway, outputs, client=("192.168.1.50", 50000)) as c:
        assert c.get("/nope").status_code == 404


def test_lan_mode_rejects_foreign_origin(service, store, gateway, outputs):
    with make_client(service, store, gateway, outputs, allow_lan=True, client=("192.168.1.50", 50000)) as c:
        r = c.post("/mcp", headers={**HEADERS, "Host": "192.168.1.5:8000", "Origin": "https://evil.example"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 403


def test_lan_mode_accepts_localhost_origin(service, store, gateway, outputs):
    with make_client(service, store, gateway, outputs, allow_lan=True, client=("192.168.1.50", 50000)) as c:
        r = c.post("/mcp", headers={**HEADERS, "Host": "192.168.1.5:8000", "Origin": "http://localhost:3000"},
                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert r.status_code == 200


def test_loopback_mode_rejects_foreign_origin(mcp):
    r = mcp.post("/mcp", headers={**HEADERS, "Origin": "https://evil.example"},
                 json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert r.status_code == 403


def test_loopback_mode_rejects_foreign_host(mcp):
    r = mcp.post("/mcp", headers={**HEADERS, "Host": "evil.example:8000"},
                 json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert 400 <= r.status_code < 500


def test_wait_does_not_block_other_requests_while_store_lock_is_held(mcp, store, running):
    held, release = threading.Event(), threading.Event()

    def hold_lock():
        with store.lock:
            held.set()
            release.wait(3)          # ปล่อยเองหลัง 3 วินาที กันค้างถ้า event loop ถูกบล็อก

    holder = threading.Thread(target=hold_lock); holder.start(); held.wait()
    cursor = len(store._events.get(running.id, []))
    result: list[str] = []
    waiter = threading.Thread(target=lambda: result.append(call(
        mcp, "series_wait", series_id=running.id, timeout_seconds=5, after_event=cursor,
    )["content"][0]["text"]))
    waiter.start()
    time.sleep(0.3)                  # ให้ series_wait เริ่มรอ lock ก่อน
    t = time.monotonic()
    assert mcp.get("/").json() == {"ok": True}
    elapsed = time.monotonic() - t
    release.set(); holder.join()
    store.save(store.get(running.id), "EP01 scene 1 DONE")
    waiter.join(10)
    assert elapsed < 1.0
    assert result and "EP01 scene 1 DONE" in result[0]


def test_wait_returns_at_once_when_series_is_not_running(mcp, service, running):
    service.control(running.id, "pause")
    t = time.monotonic()
    text = call(mcp, "series_wait", series_id=running.id, timeout_seconds=120)["content"][0]["text"]
    assert time.monotonic() - t < 1.0 and "PAUSED" in text


def test_studio_status_lists_unreadable_series_folders(mcp, store, outputs):
    bad = outputs / "series" / "broken-1"; bad.mkdir(); (bad / "series.json").write_text("{not json")
    store.load_all()
    text = call(mcp, "studio_status")["content"][0]["text"]
    assert "broken-1" in text
