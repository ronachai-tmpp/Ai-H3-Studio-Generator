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
