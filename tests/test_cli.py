import argparse

import pytest

from govee_logger.cli import interval, interval_seconds, next_run


def test_interval():
    assert interval_seconds(interval("30m")) == 1800
    assert interval_seconds(interval("24h")) == 86400
    assert interval_seconds(interval("2d")) == 172800


@pytest.mark.parametrize("value", ["", "6", "h", "1.5h", "6 h", "1w"])
def test_interval_rejects(value):
    with pytest.raises(argparse.ArgumentTypeError):
        interval(value)


def test_next_run():
    assert next_run(True, "24h", "1h") == "24h"
    assert next_run(False, "24h", "1h") == "1h"
    # A retry never waits longer than the regular interval.
    assert next_run(False, "30m", "1h") == "30m"
