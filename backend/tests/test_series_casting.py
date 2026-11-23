from __future__ import annotations

import threading
import time

import pytest

from app.services.series_runner import SeriesRunner


@pytest.fixture
def casting(service):
    s = service.create_series("x")
    service.set_character(s.id, "Mali", casting_prompt="a young woman, front view, plain wall")
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "ref", "characters": ["Mali"]}])
    return service.control(s.id, "start")


def test_casting_job_runs_before_scenes(runner, gateway, casting):
    runner.tick(); runner.tick()
    job = dict(gateway.submitted[0]); job.pop("job_id")
    assert len(gateway.submitted) == 1
    assert job == {"prompt": "a young woman, front view, plain wall", "job_type": "T2V", "megapixels": 0.35,
                   "aspect_ratio": "9:16 (Portrait Widescreen)", "duration_seconds": 5, "seed": -1,
                   "reference_names": None, "first_frame_name": None}


def test_cast_done_sets_reference_and_pauses_for_review(runner, gateway, casting, store, outputs):
    runner.tick(); gateway.finish("job-1"); runner.tick()
    s = store.get(casting.id); ref = s.characters[0].reference_images[0].path
    assert ref == f"series/{casting.id}/refs/mali_cast.jpg" and (outputs / ref).is_file()
    assert gateway.extract_calls == [("videos/job-1.mp4", ref, "last", 3)]
    assert (s.status, s.pause_reason) == ("PAUSED", "casting") and "Mali" in s.pause_message


def test_resume_after_casting_starts_scenes(service, runner, gateway, casting):
    runner.tick(); gateway.finish("job-1"); runner.tick()
    service.control(casting.id, "resume"); runner.tick()
    assert gateway.submitted[1]["job_type"] == "REF2VA"
    assert gateway.pushed == [f"series/{casting.id}/refs/mali_cast.jpg"]


def test_casting_failure_pauses_after_max_attempts(runner, gateway, casting, store):
    runner.tick(); gateway.finish("job-1", "FAILED", "boom"); runner.tick(); runner.tick()
    gateway.finish("job-2", "FAILED", "boom"); runner.tick(); runner.tick()
    s = store.get(casting.id)
    assert (s.status, s.pause_reason) == ("PAUSED", "error") and len(gateway.submitted) == 2


def test_all_characters_cast_before_pause(service, runner, gateway, store):
    s = service.create_series("x")
    service.set_character(s.id, "A", casting_prompt="a"); service.set_character(s.id, "B", casting_prompt="b")
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "ref", "characters": ["A", "B"]}])
    service.control(s.id, "start")
    runner.tick(); gateway.finish("job-1"); runner.tick()
    assert store.get(s.id).status == "RUNNING"
    runner.tick(); gateway.finish("job-2"); runner.tick()
    assert store.get(s.id).pause_reason == "casting"


def test_recast_runs_again_and_keeps_done_scenes(service, runner, gateway, casting, store):
    runner.tick(); gateway.finish("job-1"); runner.tick()
    service.control(casting.id, "resume"); runner.tick(); gateway.finish("job-2"); runner.tick(); runner.tick()
    service.set_character(casting.id, "Mali", casting_prompt="older woman")
    service.write_episode(casting.id, "two", [{"prompt": "p", "mode": "ref", "characters": ["Mali"]}])
    runner.tick()
    assert gateway.submitted[-1]["prompt"] == "older woman"
    assert store.get(casting.id).episodes[0].scenes[0].status == "DONE"


def test_thai_named_characters_get_separate_files(service, runner, gateway, store, outputs):
    s = service.create_series("x")
    service.set_character(s.id, "มะลิ", casting_prompt="a"); service.set_character(s.id, "ก้อง", casting_prompt="b")
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "ref", "characters": ["มะลิ", "ก้อง"]}])
    service.control(s.id, "start")
    runner.tick(); gateway.finish("job-1"); runner.tick(); runner.tick(); gateway.finish("job-2"); runner.tick()
    paths = [c.reference_images[0].path for c in store.get(s.id).characters]
    assert paths == [f"series/{s.id}/refs/char1_cast.jpg", f"series/{s.id}/refs/char2_cast.jpg"]
    assert all((outputs / p).is_file() for p in paths)


def test_casting_done_without_video_counts_as_failure(runner, gateway, casting, store):
    runner.tick()
    gateway.jobs["job-1"]["status"] = "DONE"  # DONE แต่ไม่มีไฟล์วิดีโอ
    runner.tick()
    ch = store.get(casting.id).characters[0]
    assert ch.casting_attempts == 1 and ch.casting_job_id is None and not ch.reference_images


def test_casting_frame_extract_failure_counts_as_failure(runner, gateway, casting, store, monkeypatch):
    runner.tick(); gateway.finish("job-1")
    monkeypatch.setattr(gateway, "extract_frame", lambda *a, **k: False)
    runner.tick()
    ch = store.get(casting.id).characters[0]
    assert ch.casting_attempts == 1 and ch.casting_job_id is None and not ch.reference_images


def test_casting_falls_back_to_offset_zero(runner, gateway, casting, store, monkeypatch):
    runner.tick(); gateway.finish("job-1")
    original = gateway.extract_frame

    def fail_offset_3(video, dest, position="last", offset=0):
        if offset == 3:
            gateway.extract_calls.append((video, dest, position, offset))
            return False
        return original(video, dest, position, offset)

    monkeypatch.setattr(gateway, "extract_frame", fail_offset_3)
    runner.tick()
    s = store.get(casting.id); ch = s.characters[0]
    ref = f"series/{casting.id}/refs/mali_cast.jpg"
    assert gateway.extract_calls == [("videos/job-1.mp4", ref, "last", 3), ("videos/job-1.mp4", ref, "last", 0)]
    assert ch.reference_images[0].path == ref and ch.casting_attempts == 0
    assert (s.status, s.pause_reason) == ("PAUSED", "casting")


def test_casting_cancelled_pauses_for_user(runner, gateway, casting, store):
    runner.tick(); gateway.finish("job-1", "CANCELLED"); runner.tick()
    s = store.get(casting.id)
    assert (s.status, s.pause_reason) == ("PAUSED", "user") and s.characters[0].casting_job_id is None


def test_casting_job_lost_after_restart_is_resubmitted(store, gateway, casting):
    runner = SeriesRunner(store, gateway); runner.tick()
    gateway.forget("job-1")
    SeriesRunner(store, gateway).tick()  # runner ใหม่ = แอปรีสตาร์ต
    assert store.get(casting.id).characters[0].casting_job_id is None
    SeriesRunner(store, gateway).tick()
    assert len(gateway.submitted) == 2


def test_thread_start_stop(store, gateway, running):
    r = SeriesRunner(store, gateway, tick_seconds=0.01)
    r.start(); r.start()
    deadline = time.monotonic() + 2
    while not gateway.submitted and time.monotonic() < deadline: time.sleep(0.01)
    r.stop()
    assert gateway.submitted and not any(t.name == "h3-series-runner" and t.is_alive() for t in threading.enumerate())


def test_tick_exception_does_not_kill_thread(store, gateway, running, monkeypatch):
    r = SeriesRunner(store, gateway, tick_seconds=0.01); calls = []
    def boom(): calls.append(1); raise RuntimeError("x")
    monkeypatch.setattr(r, "tick", boom)
    r.start(); time.sleep(0.2); r.stop()
    assert len(calls) > 1
