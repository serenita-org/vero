import os
import re
from collections.abc import AsyncGenerator
from typing import Any

import msgspec.json
import pytest
from aiointercept import CallbackResult, aiointercept
from yarl import URL

from schemas.remote_signer import HealthCheckResponse
from schemas.validator import ValidatorIndexPubkey


@pytest.fixture
async def remote_signer_mock() -> AsyncGenerator[aiointercept, None]:
    async with aiointercept() as server_mock:
        yield server_mock


@pytest.fixture
def remote_signer_url(remote_signer_mock: aiointercept) -> str:
    return remote_signer_mock.server_url


@pytest.fixture
def _mocked_remote_signer_endpoints(
    validators: list[ValidatorIndexPubkey],
    remote_signer_mock: aiointercept,
) -> None:
    def _mocked_pubkeys_endpoint(url: URL, **kwargs: Any) -> CallbackResult:
        return CallbackResult(payload=[v.pubkey for v in validators])

    def _mocked_healthcheck_endpoint(url: URL, **kwargs: Any) -> CallbackResult:
        return CallbackResult(
            body=msgspec.json.encode(HealthCheckResponse(status="UP", outcome="UP"))
        )

    def _mocked_sign_endpoint(url: URL, **kwargs: Any) -> CallbackResult:
        return CallbackResult(body="0x" + os.urandom(96).hex())

    base_url = remote_signer_mock.server_url
    remote_signer_mock.get(
        url=f"{base_url}/api/v1/eth2/publicKeys",
        callback=_mocked_pubkeys_endpoint,
        repeat=True,
    )

    remote_signer_mock.get(
        url=f"{base_url}/healthcheck",
        callback=_mocked_healthcheck_endpoint,
        repeat=True,
    )

    remote_signer_mock.post(
        url=re.compile(rf"{re.escape(base_url)}/api/v1/eth2/sign/\w{{98}}$"),
        callback=_mocked_sign_endpoint,
        repeat=True,
    )
