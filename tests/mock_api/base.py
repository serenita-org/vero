from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager

import pytest
from aiointercept import aiointercept


@asynccontextmanager
async def _mock_servers(count: int) -> AsyncGenerator[list[aiointercept], None]:
    async with AsyncExitStack() as stack:
        yield [await stack.enter_async_context(aiointercept()) for _ in range(count)]


@pytest.fixture
async def beacon_node_mocks(
    request: pytest.FixtureRequest,
) -> AsyncGenerator[list[aiointercept], None]:
    async with _mock_servers(getattr(request, "param", 1)) as server_mocks:
        yield server_mocks


@pytest.fixture
def beacon_nodes_by_name(
    beacon_node_mocks: list[aiointercept],
) -> dict[str, aiointercept]:
    return dict(zip(("a", "b", "c"), beacon_node_mocks, strict=True))


@pytest.fixture
async def proposal_beacon_node_mocks(
    request: pytest.FixtureRequest,
) -> AsyncGenerator[list[aiointercept], None]:
    async with _mock_servers(getattr(request, "param", 0)) as server_mocks:
        yield server_mocks


@pytest.fixture
async def builder_mocks(
    request: pytest.FixtureRequest,
) -> AsyncGenerator[list[aiointercept], None]:
    async with _mock_servers(getattr(request, "param", 0)) as server_mocks:
        yield server_mocks


@pytest.fixture
def beacon_node_urls(beacon_node_mocks: list[aiointercept]) -> list[str]:
    return [server_mock.server_url for server_mock in beacon_node_mocks]


@pytest.fixture
def beacon_node_urls_proposal(
    proposal_beacon_node_mocks: list[aiointercept],
) -> list[str]:
    return [server_mock.server_url for server_mock in proposal_beacon_node_mocks]


@pytest.fixture
def builder_urls(builder_mocks: list[aiointercept]) -> list[str]:
    return [server_mock.server_url for server_mock in builder_mocks]
