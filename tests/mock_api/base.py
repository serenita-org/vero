from collections.abc import AsyncGenerator

import pytest
from aiointercept import aiointercept


@pytest.fixture
async def mocked_responses() -> AsyncGenerator[aiointercept, None]:
    # Requests to Keymanager API use bare IP addresses and bypass interception
    async with aiointercept(mock_external_urls=True, passthrough=["127.0.0.1"]) as m:
        yield m
