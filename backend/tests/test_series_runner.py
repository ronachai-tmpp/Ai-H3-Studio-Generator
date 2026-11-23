"""ทดสอบ SeriesRunner.tick ด้วย FakeGateway"""

from __future__ import annotations

import threading

from app.services.series_models import waiting_for
from app.services.series_runner import SeriesRunner
from app.services.series_store import SeriesStore


def drive(runner, gateway, max_ticks=300):
    """tick จนซีรีย์นิ่ง: งานค้างในคิวปลอมถูกทำให้ DONE ทีละงาน จบเมื่อ tick 5 รอบติดไม่มีงานค้าง"""
    idle = 0
    for _ in range(max_ticks):
        runner.tick()
        open_jobs = [j for j, v in gateway.jobs.items() if v["status"] in ("PENDING", "RUNNING")]
        if open_jobs:
            idle = 0
            gateway.finish(open_jobs[0])
        else:
            idle += 1
            if idle >= 5:
                return

def test_text_scene_submits_t2v(runner, gateway, running, store):
    runner.tick()
    job = dict(gateway.submitted[0]); job_id = job.pop("job_id")
    assert job == {"prompt": running.episodes[0].scenes[0].prompt, "job_type": "T2V", "megapixels": 0.35,
                   "aspect_ratio": "9:16 (Portrait Widescreen)", "duration_seconds": 5, "seed": -1,
                   "reference_names": None, "first_frame_name": None}
    sc = store.get(running.id).episodes[0].scenes[0]
    assert (sc.status, sc.job_id) == ("QUEUED", job_id)

def test_one_job_in_flight(runner, gateway, running):
    runner.tick(); runner.tick(); runner.tick()
    assert len(gateway.submitted) == 1

def test_progress_is_mirrored(runner, gateway, running, store):
    runner.tick(); gateway.set_running("job-1", 43); runner.tick()
    sc = store.get(running.id).episodes[0].scenes[0]
    assert (sc.status, sc.progress) == ("RUNNING", 43)

def test_done_job_records_results(runner, gateway, running, store):
    runner.tick(); gateway.finish("job-1"); runner.tick()
    sc = store.get(running.id).episodes[0].scenes[0]
    assert (sc.status, sc.video_path, sc.last_frame_path, sc.thumbnail_path) == \
           ("DONE", "videos/job-1.mp4", "frames/job-1_last.jpg", "thumbnails/job-1.jpg")
    assert sc.finished_at is not None

def test_ref_scene_uses_character_images(runner, gateway, running):
    runner.tick(); gateway.finish("job-1"); runner.tick(); runner.tick()
    job = gateway.submitted[1]
    assert job["job_type"] == "REF2VA" and job["reference_names"] == ["in_1.jpg"]
    assert gateway.pushed == [f"series/{running.id}/refs/mali_1.jpg"]

def test_chain_scene_uses_previous_last_frame(runner, gateway, running):
    for _ in range(2): runner.tick(); gateway.finish(f"job-{len(gateway.submitted)}"); runner.tick()
    runner.tick()
    job = gateway.submitted[2]
    assert job["job_type"] == "FL2VA" and gateway.pushed[-1] == "frames/job-2_last.jpg"
    assert job["first_frame_name"] == "in_2.jpg"

def test_chain_extracts_missing_last_frame(runner, gateway, running, outputs):
    for _ in range(2): runner.tick(); gateway.finish(f"job-{len(gateway.submitted)}"); runner.tick()
    (outputs / "frames" / "job-2_last.jpg").unlink()
    runner.tick()
    assert gateway.extract_calls == [("videos/job-2.mp4", "frames/job-2_last.jpg", "last", 0)]

def test_chain_across_episodes(runner, gateway, running):
    drive(runner, gateway)
    ep2_first = gateway.submitted[3]
    assert ep2_first["job_type"] == "FL2VA" and gateway.pushed[-1] == "frames/job-3_last.jpg"

def test_low_vram_job_types(service, runner, gateway, tmp_path):
    s = service.create_series("x", low_vram=True)
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}]); service.control(s.id, "start")
    runner.tick()
    assert gateway.submitted[0]["job_type"] == "T2V_LOW"

def test_ref_image_pushed_once_then_again_when_comfy_changes(service, runner, gateway, tmp_path):
    img = tmp_path / "a.jpg"; img.write_bytes(b"a")
    s = service.create_series("x"); service.set_character(s.id, "mali", image_paths=[str(img)])
    ref = {"prompt": "p", "mode": "ref", "characters": ["mali"]}
    service.write_episode(s.id, "one", [ref, ref, ref, ref]); service.control(s.id, "start")
    runner.tick(); gateway.finish("job-1"); runner.tick(); runner.tick()
    assert len(gateway.pushed) == 1                                   # cache ใช้ได้
    gateway.base_url = "https://pod-8188.proxy.runpod.net"
    gateway.finish("job-2"); runner.tick(); runner.tick()
    assert len(gateway.pushed) == 2                                   # URL เปลี่ยน
    gateway.input_names.clear()
    gateway.finish("job-3"); runner.tick(); runner.tick()
    assert len(gateway.pushed) == 3                                   # ไฟล์หายจาก input

def test_failed_job_retries_then_pauses(runner, gateway, running, store):
    runner.tick(); gateway.finish("job-1", "FAILED", "CUDA out of memory"); runner.tick(); runner.tick()
    assert len(gateway.submitted) == 2 and store.get(running.id).status == "RUNNING"
    gateway.finish("job-2", "FAILED", "CUDA out of memory"); runner.tick(); runner.tick()
    s = store.get(running.id)
    assert (s.status, s.pause_reason, s.episodes[0].scenes[0].status) == ("PAUSED", "error", "FAILED")
    assert "CUDA out of memory" in s.pause_message and len(gateway.submitted) == 2

def test_cancelled_job_pauses_without_retry(runner, gateway, running, store):
    runner.tick(); gateway.finish("job-1", "CANCELLED"); runner.tick(); runner.tick()
    s = store.get(running.id)
    assert (s.status, s.pause_reason) == ("PAUSED", "user") and len(gateway.submitted) == 1

def test_missing_job_with_output_file_is_done(runner, gateway, running, store):
    runner.tick(); gateway.finish("job-1"); gateway.forget("job-1"); runner.tick()
    assert store.get(running.id).episodes[0].scenes[0].status == "DONE"

def test_missing_job_deleted_by_user_pauses(runner, gateway, running, store):
    runner.tick(); gateway.forget("job-1"); runner.tick()
    s = store.get(running.id)
    assert (s.status, s.pause_reason) == ("PAUSED", "user")

def test_missing_job_after_restart_is_resubmitted(store, gateway, running):
    SeriesRunner(store, gateway).tick(); gateway.forget("job-1")
    fresh = SeriesRunner(store, gateway); fresh.tick(); fresh.tick()
    sc = store.get(running.id).episodes[0].scenes[0]
    assert len(gateway.submitted) == 2 and sc.attempts == 0 and store.get(running.id).status == "RUNNING"

def test_episode_is_merged(runner, gateway, running, store, outputs):
    for _ in range(3): runner.tick(); gateway.finish(f"job-{len(gateway.submitted)}"); runner.tick()
    runner.tick()
    ep = store.get(running.id).episodes[0]
    assert gateway.concat_calls[0][0] == ["videos/job-1.mp4", "videos/job-2.mp4", "videos/job-3.mp4"]
    assert ep.status == "DONE" and ep.final_video_path.startswith(f"videos/series_{running.id}_ep01_")
    assert ep.thumbnail_path.startswith("thumbnails/series_") and ep.duration == 10.0
    assert (store.series_dir(running.id) / "manifest.json").is_file()

def test_single_scene_episode_skips_concat(service, runner, gateway, store):
    s = service.create_series("x"); service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    service.control(s.id, "start"); drive(runner, gateway)
    ep = store.get(s.id).episodes[0]
    assert gateway.concat_calls == [] and ep.final_video_path == "videos/job-1.mp4" and ep.status == "DONE"

def test_concat_failure_pauses_once(runner, gateway, running, store):
    gateway.concat_result = {"ok": False, "error": "ไม่พบ ffmpeg"}
    for _ in range(3): runner.tick(); gateway.finish(f"job-{len(gateway.submitted)}"); runner.tick()
    for _ in range(5): runner.tick()
    s = store.get(running.id)
    assert (s.status, s.pause_reason) == ("PAUSED", "error") and "ไม่พบ ffmpeg" in s.pause_message
    assert len(gateway.concat_calls) == 1 and s.episodes[0].status != "DONE"

def test_missing_scene_file_is_regenerated_before_merge(runner, gateway, running, store, outputs):
    for _ in range(3): runner.tick(); gateway.finish(f"job-{len(gateway.submitted)}"); runner.tick()
    (outputs / "videos" / "job-1.mp4").unlink()
    runner.tick(); runner.tick()
    assert gateway.concat_calls == [] and len(gateway.submitted) == 4
    assert store.get(running.id).episodes[0].scenes[0].status == "QUEUED"

def test_review_mode_pauses_after_episode(service, runner, gateway, store):
    s = service.create_series("x", run_mode="review")
    service.write_episode(s.id, "one", [{"prompt": "p", "mode": "text"}])
    service.write_episode(s.id, "two", [{"prompt": "p", "mode": "text"}])
    service.control(s.id, "start"); drive(runner, gateway)
    live = store.get(s.id)
    assert (live.status, live.pause_reason, [e.status for e in live.episodes]) == \
           ("PAUSED", "review", ["DONE", "PENDING"])

def test_autopilot_runs_to_done_when_story_complete(service, runner, gateway, running, store):
    service.control(running.id, "finish"); drive(runner, gateway); runner.tick()
    assert store.get(running.id).status == "DONE" and len(gateway.submitted) == 5

def test_waits_for_episodes_when_story_not_complete(runner, gateway, running, store):
    drive(runner, gateway); runner.tick()
    s = store.get(running.id)
    assert s.status == "RUNNING" and waiting_for(s) == "episodes"

def test_paused_series_is_not_advanced(service, runner, gateway, running):
    service.control(running.id, "pause"); runner.tick(); runner.tick()
    assert gateway.submitted == []

def test_stale_result_after_regenerate_is_ignored(service, runner, gateway, running, store):
    runner.tick()
    service.update_scene(running.id, 1, 1, prompt="better prompt")
    gateway.finish("job-1")
    runner.tick()
    sc = store.get(running.id).episodes[0].scenes[0]
    assert sc.job_id == "job-2" and sc.video_path is None and gateway.submitted[1]["prompt"] == "better prompt"

def test_runner_resumes_after_restart(store, gateway, running, outputs):
    r1 = SeriesRunner(store, gateway); r1.tick(); gateway.finish("job-1"); r1.tick()
    fresh_store = SeriesStore(outputs / "series"); fresh_store.load_all()
    r2 = SeriesRunner(fresh_store, gateway); r2.tick()
    assert len(gateway.submitted) == 2 and fresh_store.get(running.id).episodes[0].scenes[1].status == "QUEUED"

def test_events_are_emitted(runner, gateway, running, store):
    c = store.cursor(running.id)
    runner.tick(); gateway.finish("job-1"); runner.tick()
    _, events = store.wait_events(running.id, c, timeout=0.1)
    assert "EP01 scene 1 DONE" in events


def test_failing_series_does_not_block_others(service, runner, gateway, running, store):
    other = service.create_series("other")
    service.write_episode(other.id, "one", [{"prompt": "q", "mode": "text"}])
    service.control(other.id, "start")
    original = gateway.submit_job

    def flaky(**kw):
        if kw["prompt"] == "p1":
            raise RuntimeError("boom")
        return original(**kw)

    gateway.submit_job = flaky
    runner.tick()
    first = store.get(running.id)
    assert (first.status, first.pause_reason) == ("PAUSED", "error") and "boom" in first.pause_message
    assert [j["prompt"] for j in gateway.submitted] == ["q"]
    assert store.get(other.id).episodes[0].scenes[0].status == "QUEUED"


def test_done_job_without_video_counts_as_failure(runner, gateway, running, store):
    runner.tick(); gateway.jobs["job-1"].update(status="DONE")
    runner.tick(); runner.tick()
    assert len(gateway.submitted) == 2 and store.get(running.id).status == "RUNNING"
    gateway.jobs["job-2"].update(status="DONE"); runner.tick(); runner.tick()
    s = store.get(running.id)
    assert (s.status, s.pause_reason, s.episodes[0].scenes[0].status) == ("PAUSED", "error", "FAILED")
    assert len(gateway.submitted) == 2


def test_merge_result_dropped_when_regenerated_during_concat(service, runner, gateway, running, store):
    for _ in range(3): runner.tick(); gateway.finish(f"job-{len(gateway.submitted)}"); runner.tick()
    original = gateway.concat

    def concat_then_regenerate(paths, dest):
        service.update_scene(running.id, 1, 1, regenerate=True)
        return original(paths, dest)

    gateway.concat = concat_then_regenerate
    c = store.cursor(running.id)
    runner.tick()
    ep = store.get(running.id).episodes[0]
    _, events = store.wait_events(running.id, c, timeout=0.1)
    assert ep.status != "DONE" and ep.final_video_path is None and "EP01 DONE" not in events


def lock_is_free(lock) -> bool:
    """จริงเมื่อ thread อื่นจับ lock ได้ทันที (แปลว่า thread ที่เรียกไม่ได้ถือ lock อยู่)"""
    got: list[bool] = []

    def probe():
        ok = lock.acquire(blocking=False)
        got.append(ok)
        if ok:
            lock.release()

    t = threading.Thread(target=probe); t.start(); t.join()
    return got[0]


def record_lock_state(gateway, store, names):
    """ห่อ method ของ gateway ให้จดว่า lock ของ store ว่างไหมตอนถูกเรียก"""
    seen: dict[str, list[bool]] = {n: [] for n in names}
    for name in names:
        original = getattr(gateway, name)

        def wrapped(*a, _name=name, _original=original, **k):
            seen[_name].append(lock_is_free(store.lock))
            return _original(*a, **k)

        setattr(gateway, name, wrapped)
    return seen


def test_ref_and_chain_gateway_io_runs_outside_store_lock(runner, gateway, running, store, outputs):
    seen = record_lock_state(gateway, store, ["push_image", "comfy_input_exists", "extract_frame"])
    runner.tick(); gateway.finish("job-1"); runner.tick(); runner.tick()     # ฉาก ref
    gateway.finish("job-2"); runner.tick()
    (outputs / "frames" / "job-2_last.jpg").unlink()                       # บังคับให้ดึงเฟรมใหม่
    runner.tick()                                                           # ฉาก chain
    assert [j["job_type"] for j in gateway.submitted] == ["T2V", "REF2VA", "FL2VA"]
    assert len(seen["push_image"]) == 2 and len(seen["extract_frame"]) == 1
    assert all(all(v) for v in seen.values())


def test_reused_ref_image_check_runs_outside_store_lock(service, runner, gateway, store, tmp_path):
    img = tmp_path / "a.jpg"; img.write_bytes(b"a")
    s = service.create_series("x"); service.set_character(s.id, "mali", image_paths=[str(img)])
    ref = {"prompt": "p", "mode": "ref", "characters": ["mali"]}
    service.write_episode(s.id, "one", [ref, ref]); service.control(s.id, "start")
    runner.tick(); gateway.finish("job-1"); runner.tick()
    seen = record_lock_state(gateway, store, ["comfy_input_exists"])
    runner.tick()
    assert seen["comfy_input_exists"] == [True] and len(gateway.pushed) == 1 and len(gateway.submitted) == 2


def test_pause_during_push_drops_the_submit(service, runner, gateway, running, store):
    runner.tick(); gateway.finish("job-1"); runner.tick()
    original = gateway.push_image

    def push_then_pause(rel):
        service.control(running.id, "pause")
        return original(rel)

    gateway.push_image = push_then_pause
    runner.tick()
    s = store.get(running.id)
    assert len(gateway.submitted) == 1 and (s.status, s.pause_reason) == ("PAUSED", "user")
    assert s.episodes[0].scenes[1].job_id is None and s.episodes[0].scenes[1].status == "PENDING"


def test_push_error_pauses_series(runner, gateway, running, store):
    runner.tick(); gateway.finish("job-1"); runner.tick()

    def boom(rel):
        raise RuntimeError("upload timeout")

    gateway.push_image = boom
    runner.tick()
    s = store.get(running.id)
    assert (s.status, s.pause_reason) == ("PAUSED", "error") and "upload timeout" in s.pause_message


def test_retry_success_clears_scene_error(runner, gateway, running, store):
    runner.tick(); gateway.finish("job-1", "FAILED", "CUDA out of memory"); runner.tick()
    assert store.get(running.id).episodes[0].scenes[0].error == "CUDA out of memory"
    runner.tick(); gateway.finish("job-2"); runner.tick()
    sc = store.get(running.id).episodes[0].scenes[0]
    assert sc.status == "DONE" and sc.error is None


def test_long_job_error_is_truncated_everywhere(runner, gateway, running, store):
    c = store.cursor(running.id)
    huge = "x" * 5000
    runner.tick(); gateway.finish("job-1", "FAILED", huge); runner.tick(); runner.tick()
    gateway.finish("job-2", "FAILED", huge); runner.tick()
    s = store.get(running.id)
    _, events = store.wait_events(running.id, c, timeout=0.1)
    assert s.status == "PAUSED"
    assert len(s.episodes[0].scenes[0].error) <= 320 and s.episodes[0].scenes[0].error.endswith("…")
    assert len(s.pause_message) <= 320
    assert events and all(len(e) <= 320 for e in events)


def test_series_done_rewrites_manifest(service, runner, gateway, running, store):
    import json
    drive(runner, gateway)
    live = store.get(running.id); live.story_complete = True; store.save(live)   # ข้าม service: ทดสอบฝั่ง runner
    runner.tick()
    assert store.get(running.id).status == "DONE"
    manifest = json.loads((store.series_dir(running.id) / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["story_complete"] is True and [e["number"] for e in manifest["episodes"]] == [1, 2]


def test_character_replaced_during_upload_drops_the_stale_name(service, runner, gateway, running, store, tmp_path):
    runner.tick(); gateway.finish("job-1"); runner.tick()                 # ฉากถัดไปเป็น ref ของ mali
    new = tmp_path / "new.jpg"; new.write_bytes(b"new face")
    original = gateway.push_image
    replaced: list[str] = []

    def push_then_replace(rel):
        name = original(rel)
        if not replaced:
            replaced.append(name)
            service.set_character(running.id, "mali", image_paths=[str(new)])
        return name

    gateway.push_image = push_then_replace
    runner.tick()
    s = store.get(running.id)
    assert len(gateway.submitted) == 1 and s.episodes[0].scenes[1].job_id is None
    assert s.characters[0].reference_images[0].comfy_name is None
    runner.tick()
    assert len(gateway.pushed) == 2 and gateway.submitted[1]["job_type"] == "REF2VA"
    assert gateway.submitted[1]["reference_names"] == ["in_2.jpg"] != replaced
