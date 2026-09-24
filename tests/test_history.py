from datetime import datetime, timedelta, timezone

from govee_logger.history import (
    MAX_MINUTES,
    build_request,
    _missing_span,
    _watermark,
    minutes_to_fetch,
    parse_packet,
    supports_history,
)


def test_build_request():
    req = build_request(0x7080, 1)
    assert len(req) == 20
    assert req[:6] == bytes.fromhex("330170800001")
    assert req[6:19] == bytes(13)
    assert req[19] == 0x33 ^ 0x01 ^ 0x70 ^ 0x80 ^ 0x00 ^ 0x01


def test_parse_packet():
    data = bytes.fromhex("0010") + bytes.fromhex("037f7a") * 2 + b"\xff\xff\xff" * 4
    assert parse_packet(data) == [(16, 22.9, 24.2), (15, 22.9, 24.2)]


def test_minutes_to_fetch():
    now = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
    assert minutes_to_fetch(now, None) == MAX_MINUTES
    assert minutes_to_fetch(now, now - timedelta(hours=2)) == 120
    assert minutes_to_fetch(now, now) == 1
    assert minutes_to_fetch(now, now - timedelta(days=60)) == MAX_MINUTES


def test_supports_history():
    assert supports_history("GVH5075_ABCD")
    assert not supports_history("Govee_H5179_ABCD")



def test_missing_span_and_watermark():
    t0 = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)
    wanted = [t0 + timedelta(minutes=i) for i in range(10)]
    assert _missing_span(wanted, set()) == (wanted[0], wanted[9])
    assert _watermark(wanted, set()) is None
    covered = set(wanted[:4]) | set(wanted[6:8])
    assert _missing_span(wanted, covered) == (wanted[4], wanted[9])
    assert _watermark(wanted, covered) == wanted[3]
    assert _missing_span(wanted, set(wanted)) is None
    assert _watermark(wanted, set(wanted)) == wanted[9]
