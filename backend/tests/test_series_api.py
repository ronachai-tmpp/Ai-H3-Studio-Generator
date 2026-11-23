from __future__ import annotations

import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import series as series_router


@pytest.fixture
def client(service):
    app = FastAPI(); app.include_router(series_router.router, prefix="/api/series")
    app.dependency_overrides[series_router.get_service] = lambda: service
    return TestClient(app)


def test_list_and_detail(client, done_series):
    rows = client.get("/api/series/").json()
    assert rows[0]["id"] == done_series.id and rows[0]["episodes_done"] == 2
    d = client.get(f"/api/series/{done_series.id}").json()
    assert d["episodes"][0]["scenes"][0]["prompt"] and d["progress"]["scenes_total"] == 5


def test_unknown_series_is_404(client):
    assert client.get("/api/series/nope").status_code == 404


def test_control(client, running):
    r = client.post(f"/api/series/{running.id}/control", json={"action": "pause"})
    assert r.status_code == 200 and r.json()["status"] == "PAUSED"
    assert client.post(f"/api/series/{running.id}/control", json={"action": "pause"}).status_code == 400
    assert client.post(f"/api/series/{running.id}/control", json={"action": "start"}).status_code == 422


def test_app_lifespan_starts_and_stops_runner(monkeypatch):
    from app.main import app
    from app.services import series_runtime
    # แอปจริงชี้ outputs/ จริง: ปิด tick กันไม่ให้ test ส่งงานของซีรีย์จริงเข้า GPU
    monkeypatch.setattr(series_runtime.series_runner, "tick", lambda: None)
    with TestClient(app) as c:
        assert c.get("/api/series/").status_code == 200
        assert any(t.name == "h3-series-runner" and t.is_alive() for t in threading.enumerate())
    assert not any(t.name == "h3-series-runner" and t.is_alive() for t in threading.enumerate())
