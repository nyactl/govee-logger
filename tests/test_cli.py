import argparse

import pytest

from govee_logger.cli import interval, interval_seconds


def test_interval():
    assert interval_seconds(interval("30m")) == 1800
    assert interval_seconds(interval("24h")) == 86400
    assert interval_seconds(interval("2d")) == 172800


@pytest.mark.parametrize("value", ["", "6", "h", "1.5h", "6 h", "1w"])
def test_interval_rejects(value):
    with pytest.raises(argparse.ArgumentTypeError):
        interval(value)
