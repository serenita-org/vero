import sys


def test_gil_disabled() -> None:
    assert sys._is_gil_enabled() is False
