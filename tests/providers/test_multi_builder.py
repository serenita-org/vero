import asyncio
import re
from dataclasses import dataclass
from functools import partial
from typing import Any

import msgspec
import pytest
from aioresponses import CallbackResult, aioresponses

from args import CLIArgs
from providers import BeaconChain, MultiBuilder
from providers._headers import ETH_CONSENSUS_VERSION
from schemas import SchemaBuilderAPI, SchemaShared


@dataclass
class BuilderResponse:
    base_url: str
    status_code: int = 200
    response: SchemaBuilderAPI.GetExecutionPayloadBidResponse | None = None
    exception: Exception | None = None
    delay: float | int = 0.0


def _create_bid(
    value: int, execution_payment: int = 0
) -> SchemaShared.SignedExecutionPayloadBid:
    return SchemaShared.SignedExecutionPayloadBid(
        message=SchemaShared.ExecutionPayloadBid(
            parent_block_hash="0x" + "aa" * 32,
            parent_block_root="0x" + "bb" * 32,
            block_hash="0x" + "00" * 32,
            prev_randao="0x" + "00" * 32,
            fee_recipient="0xfee0000000000000000000000000000000000000",
            gas_limit="100000000",
            builder_index="123",
            slot="123",
            value=str(value),
            execution_payment=str(execution_payment),
            blob_kzg_commitments=[],
            execution_requests_root="0x" + "00" * 32,
        ),
        signature="0x" + "00" * 96,
    )


@pytest.mark.parametrize(
    argnames=("builder_responses", "expected_bid_total_value"),
    argvalues=[
        pytest.param(
            [
                BuilderResponse(
                    base_url="https://builder-1",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=123),
                    ),
                ),
                BuilderResponse(
                    base_url="https://builder-2",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=234),
                    ),
                ),
                BuilderResponse(
                    base_url="https://builder-3",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=321),
                    ),
                ),
            ],
            321,
            id="happy case - all builder return valid bids",
        ),
        pytest.param(
            [
                BuilderResponse(
                    base_url="https://builder-1",
                    status_code=204,
                ),
                BuilderResponse(
                    base_url="https://builder-2",
                    status_code=204,
                ),
                BuilderResponse(
                    base_url="https://builder-3",
                    status_code=204,
                ),
            ],
            None,
            id="no builder with a bid",
        ),
        pytest.param(
            [
                BuilderResponse(
                    base_url="https://builder-1",
                    response=None,
                    exception=TimeoutError(),
                ),
                BuilderResponse(
                    base_url="https://builder-2",
                    status_code=500,
                    response=None,
                    exception=None,
                ),
                BuilderResponse(
                    base_url="https://builder-3",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=123),
                    ),
                ),
            ],
            123,
            id="1 builder times out, 1 errors, one builder returns bid",
        ),
        pytest.param(
            [
                BuilderResponse(
                    base_url="https://builder-1",
                    exception=TimeoutError(),
                    delay=0.15,
                ),
                BuilderResponse(
                    base_url="https://builder-2",
                    exception=TimeoutError(),
                    delay=0.15,
                ),
                BuilderResponse(
                    base_url="https://builder-3",
                    exception=TimeoutError(),
                    delay=0.15,
                ),
            ],
            None,
            id="all builders fail between soft and hard timeout",
        ),
        pytest.param(
            [
                BuilderResponse(
                    base_url="https://builder-1",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=4),
                    ),
                    delay=0.2,
                ),
                BuilderResponse(
                    base_url="https://builder-2",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=5),
                    ),
                    delay=0.2,
                ),
                BuilderResponse(
                    base_url="https://builder-3",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=1),
                    ),
                    delay=0.1,
                ),
            ],
            1,
            id="soft timeout -> use quickest response despite lowest value",
        ),
        pytest.param(
            [
                BuilderResponse(
                    base_url="https://builder-1",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=1),
                    ),
                    delay=0.21,
                ),
                BuilderResponse(
                    base_url="https://builder-2",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=2),
                    ),
                    delay=0.21,
                ),
                BuilderResponse(
                    base_url="https://builder-3",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=3),
                    ),
                    delay=0.21,
                ),
            ],
            None,
            id="hard timeout -> do not wait indefinitely",
        ),
        pytest.param(
            [
                BuilderResponse(
                    base_url="https://builder-1",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=2),
                    ),
                ),
                BuilderResponse(
                    base_url="https://builder-2",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=3),
                    ),
                ),
                BuilderResponse(
                    base_url="https://builder-3",
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=1, execution_payment=3),
                    ),
                ),
            ],
            4,
            id="trusted bid component",
        ),
    ],
)
@pytest.mark.parametrize(
    argnames="cli_args",
    argvalues=[
        pytest.param(
            {
                "builder_urls": [
                    "https://builder-1",
                    "https://builder-2",
                    "https://builder-3",
                ],
            },
            id="3 builders",
        ),
    ],
    indirect=True,
)
async def test_bid_selection_builders(
    builder_responses: list[BuilderResponse],
    expected_bid_total_value: int,
    beacon_chain: BeaconChain,
    multi_builder: MultiBuilder,
    cli_args: CLIArgs,
) -> None:
    for builder in multi_builder.builders:
        builder._bid_request_auth_cache[(123, "0x9abc")] = (
            SchemaShared.SignedBuilderRequestAuth(
                message=SchemaShared.BuilderRequestAuth(data="0x", slot="123"),
                signature="0x" + "00" * 96,
            )
        )
    with aioresponses() as m:
        for builder_response in builder_responses:
            base_url = builder_response.base_url
            url_regex_to_mock = re.compile(
                rf"^{base_url}/eth/v1/builder/execution_payload_bid/.+",
            )

            async def _f(
                _response: SchemaBuilderAPI.GetExecutionPayloadBidResponse | None,
                _status_code: int,
                _exception: Exception | None,
                _delay: float,
                *args: Any,
                **kwargs: Any,
            ) -> CallbackResult:
                await asyncio.sleep(_delay)
                if _exception:
                    raise _exception

                _body, _headers = b"", {}
                if _response:
                    _body = msgspec.json.encode(_response)
                    _headers = {
                        ETH_CONSENSUS_VERSION: _response.version.value.lower(),
                    }
                return CallbackResult(
                    status=_status_code,
                    body=_body,
                    headers=_headers,
                )

            _callback = partial(
                _f,
                builder_response.response,
                builder_response.status_code,
                builder_response.exception,
                builder_response.delay,
            )
            m.post(
                url=url_regex_to_mock,
                callback=_callback,
            )

        bid = await multi_builder.get_execution_payload_bid(
            slot=123,
            parent_hash="0x" + "aa" * 32,
            parent_root="0x" + "bb" * 32,
            proposer_pubkey="0x9abc",
            fork_version=beacon_chain.current_fork_version,
            soft_timeout=0.1,
            hard_timeout=0.2,
        )
        if bid is None:
            assert expected_bid_total_value is None
        else:
            assert bid.total_value == expected_bid_total_value


# TODO test SSZ/JSON?
# TODO SSE bid selection
# TODO Abstract into BidProvider? BlockProposalService is getting a bit big
