from datetime import datetime, timezone

from govee_logger import store
from govee_logger.decode import Reading
from govee_logger.scanner import Sample


def sample(address, name):
    return Sample(datetime(2026, 9, 25, 8, 0, 30, tzinfo=timezone.utc), address, name, -60, Reading(21.5, 48.0, 90))


def test_label_from_aliases(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.record_samples(conn, [sample("AA", "GVH5075_AAAA"), sample("BB", "GVH5075_BBBB")], {"AA": "Kitchen"})
    labels = {r["address"]: r["label"] for r in store.latest(conn)}
    assert labels == {"AA": "Kitchen", "BB": "GVH5075_BBBB"}

    store.record_samples(conn, [sample("AA", "GVH5075_AAAA")], {})
    assert store.latest(conn)[0]["label"] == "GVH5075_AAAA"


def test_readings_are_minute_aligned_and_deduplicated(tmp_path):
    conn = store.connect(tmp_path / "t.db")
    store.record_samples(conn, [sample("AA", "GVH5075_AAAA")], {})
    store.record_samples(conn, [sample("AA", "GVH5075_AAAA")], {})
    rows = store.history(conn, None)
    assert [(r["ts"], r["temperature"]) for r in rows] == [("2026-09-25T08:00:00+00:00", 21.5)]
