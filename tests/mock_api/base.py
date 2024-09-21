from collections.abc import Generator

import pytest
from aioresponses import aioresponses


@pytest.fixture
def mocked_responses() -> Generator[aioresponses, None, None]:
    with aioresponses() as m:
        yield m
