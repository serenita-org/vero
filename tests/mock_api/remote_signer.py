import os
import re
from typing import TYPE_CHECKING, Any

import pytest
from aioresponses import CallbackResult, aioresponses

if TYPE_CHECKING:
    from yarl import URL

    from schemas.validator import ValidatorIndexPubkey


@pytest.fixture(scope="session")
def remote_signer_url() -> str:
    return "http://remote-signer:1234"


@pytest.fixture
def _mocked_remote_signer_endpoints(
    validators: list[ValidatorIndexPubkey],
    mocked_responses: aioresponses,
) -> None:
    def _mocked_pubkeys_endpoint(url: URL, **kwargs: Any) -> CallbackResult:
        return CallbackResult(payload=[v.pubkey for v in validators])

    def _mocked_sign_endpoint(url: URL, **kwargs: Any) -> CallbackResult:
        return CallbackResult(payload={"signature": "0x" + os.urandom(96).hex()})

    mocked_responses.get(
        url=re.compile("http://remote-signer:1234/api/v1/eth2/publicKeys"),
        callback=_mocked_pubkeys_endpoint,
        repeat=True,
    )

    mocked_responses.post(
        url=re.compile("http://remote-signer:1234/api/v1/eth2/sign/\\w{98}$"),
        callback=_mocked_sign_endpoint,
        repeat=True,
    )
