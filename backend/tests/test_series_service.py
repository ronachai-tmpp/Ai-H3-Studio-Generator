from __future__ import annotations

import pytest

from app.services.series_models import SeriesError


def test_create_defaults(service):
    s = service.create_series("Love Story")
    assert (s.aspect_ratio, s.megapixels, s.run_mode, s.status, s.max_attempts) == \
           ("9:16 (Portrait Widescreen)", 0.35, "autopilot", "DRAFT", 2)

def test_create_rejects_bad_megapixels(service):
    with pytest.raises(SeriesError): service.create_series("x", megapixels=0.4)

def test_set_character_copies_image(service, outputs, tmp_path):
    s = service.create_series("x"); src = tmp_path / "face.png"; src.write_bytes(b"png")
    c = service.set_character(s.id, "Mali", image_paths=[str(src)])
    assert c.reference_images[0].path == f"series/{s.id}/refs/mali_1.png"
    assert (outputs / c.reference_images[0].path).read_bytes() == b"png" and src.exists()

def test_set_character_accepts_outputs_relative_path(service, outputs):
    s = service.create_series("x"); (outputs / "frames" / "f.jpg").write_bytes(b"j")
    assert service.set_character(s.id, "Mali", image_paths=["frames/f.jpg"]).reference_images

def test_set_character_replaces_image_set(service, tmp_path):
    s = service.create_series("x"); a = tmp_path / "a.jpg"; a.write_bytes(b"a")
    service.set_character(s.id, "Mali", image_paths=[str(a), str(a)])
    assert len(service.set_character(s.id, "Mali", image_paths=[str(a)]).reference_images) == 1

@pytest.mark.parametrize("make", ["missing", "not_image", "too_big"])
def test_set_character_rejects_bad_image(service, store, tmp_path, make):
    s = service.create_series("x")
    p = tmp_path / ("a.txt" if make == "not_image" else "a.jpg")
    if make != "missing": p.write_bytes(b"x" * (2_000_000 if make == "too_big" else 10))
    with pytest.raises(SeriesError): service.set_character(s.id, "Mali", image_paths=[str(p)])
    assert store.get(s.id).characters == []

def test_recast_clears_images_and_keeps_done_scenes(service, done_series):
    c = service.set_character(done_series.id, "mali", casting_prompt="new face")
    assert c.reference_images == [] and c.casting_prompt == "new face"
    assert service.detail(done_series.id)["episodes"][0]["scenes"][1]["status"] == "DONE"

def test_write_episode_appends_and_numbers(service):
    s = service.create_series("x")
    e1 = service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    e2 = service.write_episode(s.id, "two", [{"prompt": "p", "mode": "chain"}, {"prompt": "q", "mode": "text"}])
    assert (e1.number, e2.number, [x.index for x in e2.scenes]) == (1, 2, [1, 2])

def test_write_episode_replace_only_if_not_started(service, store):
    s = service.create_series("x")
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    assert service.write_episode(s.id, "one b", [{"prompt": "p2", "mode": "text"}], episode_number=1).title == "one b"
    live = store.get(s.id); live.episodes[0].scenes[0].status = "QUEUED"; store.save(live)
    with pytest.raises(SeriesError):
        service.write_episode(s.id, "again", [{"prompt": "p", "mode": "text"}], episode_number=1)

def test_invalid_episode_leaves_series_unchanged(service, store):
    s = service.create_series("x")
    with pytest.raises(SeriesError): service.write_episode(s.id, "one", [{"prompt": "p", "mode": "chain"}])
    assert store.get(s.id).episodes == []

def test_edit_pending_scene_resets_nothing(service):
    s = service.create_series("x"); service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    assert service.update_scene(s.id, 1, 1, prompt="new") == []
    assert service.detail(s.id)["episodes"][0]["scenes"][0]["prompt"] == "new"

def test_regenerate_resets_following_chain_scenes_across_episodes(service, store, done_series, outputs):
    old = done_series.episodes[0].scenes[1].video_path
    assert service.update_scene(done_series.id, 1, 2, regenerate=True) == [(1, 2), (1, 3), (2, 1)]
    s = store.get(done_series.id)
    assert s.episodes[1].scenes[1].status == "DONE"
    assert [e.status for e in s.episodes] == ["PENDING", "PENDING"]
    assert s.episodes[0].final_video_path is None
    assert (outputs / old).exists()                 # ไฟล์เก่าไม่ถูกลบ
    assert s.status == "RUNNING" and s.story_complete is True

def test_regenerate_queued_scene_cancels_job(service, store, gateway):
    s = service.create_series("x"); service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    live = store.get(s.id); sc = live.episodes[0].scenes[0]
    sc.status, sc.job_id = "QUEUED", "job-9"; store.save(live)
    service.update_scene(s.id, 1, 1, prompt="new")
    assert gateway.cancelled == ["job-9"] and store.get(s.id).episodes[0].scenes[0].job_id is None

def test_regenerate_status_rules(service, store, done_series):
    live = store.get(done_series.id); live.status, live.pause_reason = "PAUSED", "user"; store.save(live)
    service.update_scene(done_series.id, 1, 1, regenerate=True)
    assert store.get(done_series.id).status == "PAUSED"
    live = store.get(done_series.id); live.status = "CANCELLED"; store.save(live)
    with pytest.raises(SeriesError): service.update_scene(done_series.id, 1, 1, regenerate=True)

def test_write_episode_reopens_done_series(service, store, done_series):
    service.write_episode(done_series.id, "three", [{"prompt": "p", "mode": "text"}])
    assert store.get(done_series.id).status == "RUNNING"

def test_control_transitions(service, store):
    s = service.create_series("x")
    with pytest.raises(SeriesError): service.control(s.id, "start")          # ไม่มีตอน
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    assert service.control(s.id, "start").status == "RUNNING"
    with pytest.raises(SeriesError): service.control(s.id, "start")
    p = service.control(s.id, "pause"); assert (p.status, p.pause_reason) == ("PAUSED", "user")
    r = service.control(s.id, "resume"); assert (r.status, r.pause_reason) == ("RUNNING", None)
    assert service.control(s.id, "finish").story_complete is True
    assert service.control(s.id, "cancel").status == "CANCELLED"
    with pytest.raises(SeriesError): service.control(s.id, "resume")

def test_resume_from_error_resets_failed_scenes(service, store):
    s = service.create_series("x"); service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    live = store.get(s.id); live.status, live.pause_reason = "PAUSED", "error"
    sc = live.episodes[0].scenes[0]; sc.status, sc.attempts, sc.error = "FAILED", 2, "boom"; store.save(live)
    service.control(s.id, "resume")
    sc = store.get(s.id).episodes[0].scenes[0]
    assert (sc.status, sc.attempts, sc.error) == ("PENDING", 0, None)

def test_cancel_cancels_in_flight_job(service, store, gateway):
    s = service.create_series("x"); service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    service.control(s.id, "start")
    live = store.get(s.id); live.episodes[0].scenes[0].job_id = "job-3"; live.episodes[0].scenes[0].status = "RUNNING"; store.save(live)
    service.control(s.id, "cancel")
    assert gateway.cancelled == ["job-3"]

def test_detail_and_overview(service, done_series):
    d = service.detail(done_series.id)
    assert d["progress"]["scenes_done"] == 5 and d["waiting_for"] is None
    row = service.overview()[0]
    assert (row["id"], row["episodes_done"], row["episodes_total"]) == (done_series.id, 2, 2)


def test_set_character_accepts_its_own_ref_image(service, outputs, tmp_path):
    s = service.create_series("x"); a = tmp_path / "a.png"; a.write_bytes(b"A")
    c = service.set_character(s.id, "Mali", image_paths=[str(a)])
    again = service.set_character(s.id, "Mali", image_paths=[c.reference_images[0].path])
    assert again.reference_images[0].path == c.reference_images[0].path
    assert (outputs / again.reference_images[0].path).read_bytes() == b"A"


def test_set_character_swapped_own_refs_do_not_cross_overwrite(service, outputs, tmp_path):
    s = service.create_series("x")
    a = tmp_path / "a.png"; a.write_bytes(b"A")
    b = tmp_path / "b.png"; b.write_bytes(b"B")
    c = service.set_character(s.id, "Mali", image_paths=[str(a), str(b)])
    p1, p2 = (r.path for r in c.reference_images)
    c = service.set_character(s.id, "Mali", image_paths=[p2, p1])
    assert (outputs / p1).read_bytes() == b"B" and (outputs / p2).read_bytes() == b"A"


def test_cancel_failure_is_logged_not_raised(service, store, gateway, caplog):
    s = service.create_series("x"); service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    service.control(s.id, "start")
    live = store.get(s.id); sc = live.episodes[0].scenes[0]; sc.job_id, sc.status = "job-3", "RUNNING"; store.save(live)
    def boom(job_id): raise RuntimeError("comfy down")
    gateway.cancel_job = boom
    with caplog.at_level("WARNING"):
        assert service.control(s.id, "cancel").status == "CANCELLED"
    assert any("job-3" in r.getMessage() and r.levelname == "WARNING" for r in caplog.records)
