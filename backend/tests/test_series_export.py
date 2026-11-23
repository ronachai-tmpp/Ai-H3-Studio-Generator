from __future__ import annotations

import json

import pytest

from app.services.series_export import (
    build_manifest,
    export_series,
    review_images,
    safe_filename,
)
from app.services.series_models import SeriesError


def test_manifest_lists_done_episodes(done_series):
    m = build_manifest(done_series)
    assert [e["number"] for e in m["episodes"]] == [1, 2]
    assert m["episodes"][0]["video"] == done_series.episodes[0].final_video_path
    assert set(m["episodes"][0]) == {"number", "title", "synopsis", "caption", "hashtags", "video", "thumbnail", "duration"}


def test_manifest_skips_unfinished_episodes(done_series):
    done_series.episodes[1].status = "PENDING"
    assert [e["number"] for e in build_manifest(done_series)["episodes"]] == [1]


def test_safe_filename():
    assert safe_filename('ตอน: "แรก"?') == "ตอน แรก"
    assert safe_filename("a/b\\c. ") == "a b c"
    assert safe_filename('<>:"/\\|?*') == ""


def test_export_copies_with_clean_names(store, outputs, done_series):
    live = store.get(done_series.id)
    live.episodes[0].title = 'เจอกัน: "ครั้งแรก"'; live.episodes[1].title = "???"; store.save(live)
    out = export_series(store, outputs, done_series.id)
    assert out["dir"] == f"series/{done_series.id}/export"
    assert sorted(out["files"]) == ["EP01 - เจอกัน ครั้งแรก.mp4", "EP01.jpg", "EP02.jpg", "EP02.mp4", "manifest.json"]
    m = json.loads((outputs / out["dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert m["episodes"][0]["video"] == "EP01 - เจอกัน ครั้งแรก.mp4"


def test_export_skips_missing_thumbnail(store, outputs, done_series):
    (outputs / done_series.episodes[1].thumbnail_path).unlink()
    out = export_series(store, outputs, done_series.id)
    assert "EP02.jpg" not in out["files"] and "EP02 - EP2.mp4" in out["files"]
    m = json.loads((outputs / out["dir"] / "manifest.json").read_text(encoding="utf-8"))
    assert m["episodes"][1]["thumbnail"] is None


def test_export_without_done_episode_raises(store, outputs, make_series):
    s = make_series(); store.add(s)
    with pytest.raises(SeriesError): export_series(store, outputs, s.id)


def test_review_scene_samples_frames(store, gateway, done_series, outputs):
    text, images = review_images(store, gateway, done_series.id, episode=1, scene=2, frames=3)
    assert len(images) == 3 and all((outputs / p).is_file() for p in images)
    assert done_series.episodes[0].scenes[1].prompt in text


def test_review_frames_clamped(store, gateway, done_series):
    assert len(review_images(store, gateway, done_series.id, episode=1, scene=1, frames=99)[1]) == 8


def test_review_episode_returns_last_frames(store, gateway, done_series):
    _, images = review_images(store, gateway, done_series.id, episode=1)
    assert images == [s.last_frame_path for s in done_series.episodes[0].scenes]


def test_review_character_returns_reference_images(store, gateway, done_series):
    assert review_images(store, gateway, done_series.id, character="mali")[1] == \
           ["series/demo-abc123/refs/mali_1.jpg"]


def test_review_rejects_bad_requests(store, gateway, done_series, make_series):
    with pytest.raises(SeriesError): review_images(store, gateway, done_series.id)
    with pytest.raises(SeriesError): review_images(store, gateway, done_series.id, episode=1, character="mali")
    with pytest.raises(SeriesError): review_images(store, gateway, done_series.id, episode=9)
    live = store.get(done_series.id); live.episodes[0].scenes[0].status = "PENDING"; store.save(live)
    with pytest.raises(SeriesError): review_images(store, gateway, done_series.id, episode=1, scene=1)
