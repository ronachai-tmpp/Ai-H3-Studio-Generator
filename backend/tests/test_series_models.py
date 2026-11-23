from __future__ import annotations

import re

from app.services.series_models import (
    RefImage,
    Scene,
    job_type_for,
    new_series_id,
    progress_of,
    validate_series,
    waiting_for,
)


def test_job_type_for():
    assert job_type_for("text", False) == "T2V"
    assert job_type_for("ref", False) == "REF2VA"
    assert job_type_for("chain", False) == "FL2VA"
    assert job_type_for("chain", True) == "FL2VA_LOW"


def test_default_series_is_valid(make_series):
    assert validate_series(make_series()) == []


def test_first_scene_of_first_episode_cannot_chain(make_series):
    s = make_series(); s.episodes[0].scenes[0].mode = "chain"
    assert len(validate_series(s)) == 1


def test_ref_scene_needs_known_character_with_image_or_casting(make_series):
    s = make_series(); s.episodes[0].scenes[1].characters = ["nobody"]
    assert validate_series(s)
    s.episodes[0].scenes[1].characters = []
    assert validate_series(s)
    s.episodes[0].scenes[1].characters = ["mali"]
    s.characters[0].reference_images = []
    assert validate_series(s)
    s.characters[0].casting_prompt = "a young woman"
    assert validate_series(s) == []


def test_duration_and_megapixels_must_be_allowed(make_series):
    s = make_series(megapixels=0.4); assert validate_series(s)
    s = make_series(); s.episodes[0].scenes[0].duration_seconds = 7
    assert validate_series(s)


def test_scene_count_limit(make_series):
    s = make_series()
    s.episodes[0].scenes = [Scene(index=i, prompt="p", mode="text") for i in range(1, 22)]
    assert validate_series(s)


def test_reference_image_limit(make_series):
    s = make_series()
    s.characters[0].reference_images = [RefImage(path=f"series/x/refs/{i}.jpg") for i in range(10)]
    assert validate_series(s)


def test_new_series_id():
    assert re.fullmatch(r"love-story-[0-9a-f]{6}", new_series_id("Love Story!"))
    assert re.fullmatch(r"series-[0-9a-f]{6}", new_series_id("รักข้ามเวลา"))
    assert re.fullmatch(r"series-[0-9a-f]{6}", new_series_id('<>:"/\\|?*'))


def test_waiting_for(make_series):
    s = make_series(status="RUNNING")
    assert waiting_for(s) is None
    for e in s.episodes: e.status = "DONE"
    assert waiting_for(s) == "episodes"
    s.story_complete = True
    assert waiting_for(s) is None


def test_progress_of(make_series):
    s = make_series()
    a, b = s.episodes[0].scenes[0], s.episodes[0].scenes[1]
    a.status = b.status = "DONE"
    a.started_at, a.finished_at = 0.0, 100.0
    b.started_at, b.finished_at = 100.0, 300.0
    assert progress_of(s) == {"scenes_done": 2, "scenes_total": 5,
                              "avg_scene_seconds": 150.0, "eta_seconds": 450.0}


def test_progress_of_has_no_eta_when_nothing_remains(make_series):
    s = make_series()
    for e in s.episodes:
        for sc in e.scenes:
            sc.status, sc.started_at, sc.finished_at = "DONE", 0.0, 60.0
    assert progress_of(s)["eta_seconds"] is None
