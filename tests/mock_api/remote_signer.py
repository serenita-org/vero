import re
from typing import TYPE_CHECKING, Any

import milagro_bls_binding as bls
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
    validator_privkeys: list[bytes],
    validators: list[ValidatorIndexPubkey],
    mocked_responses: aioresponses,
) -> None:
    def _mocked_pubkeys_endpoint(url: URL, **kwargs: Any) -> CallbackResult:
        return CallbackResult(payload=[v.pubkey for v in validators])

    def _mocked_sign_endpoint(url: URL, **kwargs: Any) -> CallbackResult:
        url_pubkey = str(url).split("/")[-1]

        privkey = None
        for idx, validator in enumerate(validators):
            if validator.pubkey == url_pubkey:
                privkey = validator_privkeys[idx]

        if privkey is None:
            raise ValueError(f"No private key found for {url_pubkey}")

        signature = bls.Sign(privkey, kwargs["data"])
        return CallbackResult(payload={"signature": f"0x{signature.hex()}"})

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
