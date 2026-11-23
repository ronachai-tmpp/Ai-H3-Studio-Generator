from __future__ import annotations

import time

import pytest

from app.services.series_models import SeriesError
from app.services.series_store import SeriesStore


def test_roundtrip(store, make_series, outputs):
    store.add(make_series())
    fresh = SeriesStore(outputs / "series"); fresh.load_all()
    assert fresh.get("demo-abc123").episodes[1].scenes[0].mode == "chain"


def test_save_leaves_no_temp_file(store, make_series):
    s = make_series(); store.add(s); store.save(s)
    assert [p.name for p in store.series_dir(s.id).iterdir() if p.is_file()] == ["series.json"]


def test_corrupt_file_is_skipped(store, make_series, outputs):
    store.add(make_series())
    bad = outputs / "series" / "bad"; bad.mkdir(); (bad / "series.json").write_text("{not json")
    fresh = SeriesStore(outputs / "series"); fresh.load_all()
    assert [s.id for s in fresh.list()] == ["demo-abc123"]
    assert fresh.load_errors == ["bad"]


def test_get_unknown_raises(store):
    with pytest.raises(SeriesError): store.get("nope")


def test_wait_events_returns_new_events(store, make_series):
    s = make_series(); store.add(s)
    c = store.cursor(s.id)
    store.save(s, event="EP01 scene 1 DONE")
    assert store.wait_events(s.id, c, timeout=1.0) == (c + 1, ["EP01 scene 1 DONE"])


def test_wait_events_times_out(store, make_series):
    s = make_series(); store.add(s)
    c = store.cursor(s.id); t = time.monotonic()
    assert store.wait_events(s.id, c, timeout=0.2) == (c, [])
    assert time.monotonic() - t < 1.0


def test_save_without_event_does_not_wake_waiters(store, make_series):
    s = make_series(); store.add(s); c = store.cursor(s.id)
    store.save(s)
    assert store.cursor(s.id) == c
