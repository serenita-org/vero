from typing import TYPE_CHECKING

import pytest
from aioresponses import aioresponses

if TYPE_CHECKING:
    from collections.abc import Generator


@pytest.fixture
def mocked_responses() -> Generator[aioresponses]:
    # Passthrough for requests to Keymanager API
    with aioresponses(passthrough=["http://127.0.0.1"]) as m:
        yield m
