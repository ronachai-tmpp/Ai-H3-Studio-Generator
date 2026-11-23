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


def _service(store, gateway, outputs, allow_external):
    from app.services.series_service import SeriesService
    return SeriesService(store, gateway, outputs, [".png", ".jpg"], 1_000_000,
                         allow_external_images=allow_external)


def test_lan_mode_rejects_external_image_and_accepts_outputs_path(store, gateway, outputs, tmp_path):
    svc = _service(store, gateway, outputs, False)
    s = svc.create_series("x"); src = tmp_path / "face.jpg"; src.write_bytes(b"j")
    (outputs / "frames" / "f.jpg").write_bytes(b"j")
    with pytest.raises(SeriesError, match="outputs/"):
        svc.set_character(s.id, "Mali", image_paths=[str(src)])
    assert svc.set_character(s.id, "Mali", image_paths=["frames/f.jpg"]).reference_images


@pytest.mark.parametrize("allow_external", [True, False])
def test_relative_path_cannot_escape_outputs(store, gateway, outputs, allow_external):
    svc = _service(store, gateway, outputs, allow_external)
    (outputs.parent / "x.jpg").write_bytes(b"j")
    s = svc.create_series("x")
    with pytest.raises(SeriesError):
        svc.set_character(s.id, "Mali", image_paths=["../x.jpg"])


def test_write_episode_rejects_unknown_scene_key(service):
    s = service.create_series("x")
    with pytest.raises(SeriesError, match="duration"):
        service.write_episode(s.id, "e", [{"prompt": "p", "mode": "text", "duration": 8}])


def test_write_episode_ignores_index_key(service):
    s = service.create_series("x")
    ep = service.write_episode(s.id, "e", [{"index": 7, "prompt": "p", "mode": "text"}])
    assert ep.scenes[0].index == 1


def test_cancel_resets_in_flight_scenes_and_casting(service, store, gateway):
    s = service.create_series("x")
    service.set_character(s.id, "Mali", casting_prompt="a face")
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}, {"prompt": "q", "mode": "text"}])
    service.control(s.id, "start")
    live = store.get(s.id)
    sc = live.episodes[0].scenes[0]; sc.job_id, sc.status, sc.progress = "job-3", "RUNNING", 43
    live.characters[0].casting_job_id = "job-4"; store.save(live)
    service.control(s.id, "cancel")
    s2 = store.get(s.id); sc = s2.episodes[0].scenes[0]
    assert (s2.status, sc.status, sc.progress, sc.job_id) == ("CANCELLED", "PENDING", 0, None)
    assert s2.characters[0].casting_job_id is None and sorted(gateway.cancelled) == ["job-3", "job-4"]


def test_cancelled_series_rejects_plain_scene_edit(service, store):
    s = service.create_series("x"); service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    service.control(s.id, "cancel")
    with pytest.raises(SeriesError, match="ยกเลิก"):
        service.update_scene(s.id, 1, 1, prompt="new")
    assert store.get(s.id).episodes[0].scenes[0].prompt == "p"


def test_cancelled_series_rejects_character_edit(service, store, tmp_path):
    s = service.create_series("x"); service.control(s.id, "cancel")
    with pytest.raises(SeriesError, match="ยกเลิก"):
        service.set_character(s.id, "Mali", casting_prompt="a face")
    assert store.get(s.id).characters == []


def test_lan_mode_rejects_unc_path_without_touching_it(store, gateway, outputs, monkeypatch):
    from pathlib import Path
    svc = _service(store, gateway, outputs, False)
    s = svc.create_series("x")
    unc = "\\\\host\\share\\x.jpg"
    assert Path(unc).is_absolute()

    def guard(name):
        original = getattr(Path, name)

        def checked(self, *a, **k):
            assert "host" not in str(self), f"Path.{name} touched {self}"
            return original(self, *a, **k)
        monkeypatch.setattr(Path, name, checked)

    for name in ("resolve", "exists", "is_file", "stat"):
        guard(name)
    with pytest.raises(SeriesError, match="outputs/"):
        svc.set_character(s.id, "Mali", image_paths=[unc])


def test_scene_errors_name_episode_and_scene(service):
    s = service.create_series("x")
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    with pytest.raises(SeriesError, match="ตอนที่ 2 ฉากที่ 2"):
        service.write_episode(s.id, "two", [{"prompt": "p", "mode": "text"},
                                            {"prompt": "q", "mode": "text", "duration_seconds": "long"}])
    with pytest.raises(SeriesError, match="ตอนที่ 2 ฉากที่ 1"):
        service.write_episode(s.id, "two", [{"prompt": "p", "mode": "text", "length": 8}])
    with pytest.raises(SeriesError, match="ตอนที่ 1 ฉากที่ 1"):
        service.update_scene(s.id, 1, 1, mode="video")


def test_create_series_skips_a_taken_id(service, store, monkeypatch):
    from app.services import series_service as mod
    taken = service.create_series("x").id
    ids = iter([taken, "fresh-000001"])
    monkeypatch.setattr(mod, "new_series_id", lambda title: next(ids))
    assert service.create_series("y").id == "fresh-000001"
    assert store.get(taken).title == "x"


def test_create_series_skips_an_existing_folder(service, store, monkeypatch):
    from app.services import series_service as mod
    store.series_dir("orphan-000001").mkdir(parents=True)
    ids = iter(["orphan-000001", "fresh-000002"])
    monkeypatch.setattr(mod, "new_series_id", lambda title: next(ids))
    assert service.create_series("y").id == "fresh-000002"


def _manifest(store, series_id):
    import json
    return json.loads((store.series_dir(series_id) / "manifest.json").read_text(encoding="utf-8"))


def test_finish_rewrites_manifest(service, store, done_series):
    live = store.get(done_series.id); live.story_complete = False; store.save(live)
    service.control(done_series.id, "finish")
    m = _manifest(store, done_series.id)
    assert m["story_complete"] is True and [e["number"] for e in m["episodes"]] == [1, 2]


def test_regenerate_drops_episode_from_manifest(service, store, done_series):
    service.update_scene(done_series.id, 2, 2, regenerate=True)
    assert [e["number"] for e in _manifest(store, done_series.id)["episodes"]] == [1]
