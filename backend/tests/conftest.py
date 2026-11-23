from __future__ import annotations

from pathlib import Path

import pytest

from app.services.series_models import Character, Episode, RefImage, Scene, Series
from app.services.series_store import SeriesStore


@pytest.fixture
def outputs(tmp_path) -> Path:
    """โฟลเดอร์ outputs ชั่วคราว"""
    root = tmp_path / "outputs"
    for name in ("videos", "frames", "thumbnails", "series"):
        (root / name).mkdir(parents=True)
    return root


@pytest.fixture
def store(outputs) -> SeriesStore:
    return SeriesStore(outputs / "series")


@pytest.fixture
def make_series(outputs):
    """สร้าง Series ตัวอย่าง (ยังไม่ถูกเพิ่มเข้า store)"""

    def _make(**overrides) -> Series:
        ref = "series/demo-abc123/refs/mali_1.jpg"
        ref_file = outputs / ref
        ref_file.parent.mkdir(parents=True, exist_ok=True)
        ref_file.write_bytes(b"jpg")
        data = dict(
            id="demo-abc123",
            title="Demo",
            characters=[Character(name="mali", reference_images=[RefImage(path=ref)])],
            episodes=[
                Episode(number=1, title="EP1", scenes=[
                    Scene(index=1, prompt="p1", mode="text"),
                    Scene(index=2, prompt="p2", mode="ref", characters=["mali"]),
                    Scene(index=3, prompt="p3", mode="chain"),
                ]),
                Episode(number=2, title="EP2", scenes=[
                    Scene(index=1, prompt="p4", mode="chain"),
                    Scene(index=2, prompt="p5", mode="text"),
                ]),
            ],
            created_at=1000.0,
            updated_at=1000.0,
        )
        data.update(overrides)
        return Series(**data)

    return _make


@pytest.fixture
def gateway(outputs):
    from tests.fakes import FakeGateway

    return FakeGateway(outputs)


@pytest.fixture
def service(store, gateway, outputs):
    from app.services.series_service import SeriesService

    return SeriesService(store, gateway, outputs, [".png", ".jpg", ".jpeg", ".webp"], 1_000_000)


@pytest.fixture
def done_series(service, store, gateway, make_series, outputs) -> Series:
    """ซีรีส์ตัวอย่างที่ทุกฉากและทุกตอน DONE (ไฟล์จริงจาก FakeGateway.finish)"""
    series = make_series()
    for episode in series.episodes:
        for scene in episode.scenes:
            job_id = gateway.submit_job(
                prompt=scene.prompt, job_type="T2V", megapixels=series.megapixels,
                aspect_ratio=series.aspect_ratio, duration_seconds=scene.duration_seconds,
                seed=scene.seed,
            )
            gateway.finish(job_id)
            snap = gateway.get_job(job_id)
            scene.status = "DONE"
            scene.job_id = job_id
            scene.progress = 100
            scene.video_path = snap["video_path"]
            scene.thumbnail_path = snap["thumbnail_path"]
            scene.last_frame_path = f"frames/{job_id}_last.jpg"
            scene.started_at = snap["started_at"]
            scene.finished_at = snap["finished_at"]
        final = f"videos/series_{series.id}_ep{episode.number:02d}_final.mp4"
        thumb = f"thumbnails/series_{series.id}_ep{episode.number:02d}_final.jpg"
        for rel in (final, thumb):
            (outputs / rel).write_bytes(b"x")
        episode.status = "DONE"
        episode.final_video_path = final
        episode.thumbnail_path = thumb
        episode.duration = 10.0
    series.status = "DONE"
    series.story_complete = True
    store.add(series)
    return series


@pytest.fixture
def runner(store, gateway):
    from app.services.series_runner import SeriesRunner

    return SeriesRunner(store, gateway)


@pytest.fixture
def running(service, tmp_path) -> Series:
    """ซีรีส์ที่เริ่มรันแล้ว: ตัวละคร mali 1 รูป กับ 2 ตอน (text/ref/chain และ chain/text)"""
    image = tmp_path / "mali.jpg"
    image.write_bytes(b"jpg")
    series = service.create_series("Demo")
    service.set_character(series.id, "mali", image_paths=[str(image)])
    service.write_episode(series.id, "EP1", [
        {"prompt": "p1", "mode": "text"},
        {"prompt": "p2", "mode": "ref", "characters": ["mali"]},
        {"prompt": "p3", "mode": "chain"},
    ])
    service.write_episode(series.id, "EP2", [
        {"prompt": "p4", "mode": "chain"},
        {"prompt": "p5", "mode": "text"},
    ])
    return service.control(series.id, "start")
