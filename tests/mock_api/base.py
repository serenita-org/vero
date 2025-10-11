from collections.abc import Generator

import pytest
from aioresponses import aioresponses


@pytest.fixture
def mocked_responses() -> Generator[aioresponses]:
    # Passthrough for requests to Keymanager API
    with aioresponses(passthrough=["http://127.0.0.1"]) as m:
        yield m
