import asyncio
import re
from dataclasses import dataclass
from functools import partial
from typing import Any

import msgspec
import pytest
from aiointercept import CallbackResult, aiointercept

from providers import BeaconChain, MultiBuilder
from providers._headers import ETH_CONSENSUS_VERSION
from schemas import SchemaBuilderAPI, SchemaShared


@dataclass
class BuilderResponse:
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
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=123),
                    ),
                ),
                BuilderResponse(
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=234),
                    ),
                ),
                BuilderResponse(
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
                    status_code=204,
                ),
                BuilderResponse(
                    status_code=204,
                ),
                BuilderResponse(
                    status_code=204,
                ),
            ],
            None,
            id="no builder with a bid",
        ),
        pytest.param(
            [
                BuilderResponse(
                    response=None,
                    exception=TimeoutError(),
                ),
                BuilderResponse(
                    status_code=500,
                    response=None,
                    exception=None,
                ),
                BuilderResponse(
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
                    exception=TimeoutError(),
                    delay=0.15,
                ),
                BuilderResponse(
                    exception=TimeoutError(),
                    delay=0.15,
                ),
                BuilderResponse(
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
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=4),
                    ),
                    delay=0.2,
                ),
                BuilderResponse(
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=5),
                    ),
                    delay=0.2,
                ),
                BuilderResponse(
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
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=1),
                    ),
                    delay=0.21,
                ),
                BuilderResponse(
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=2),
                    ),
                    delay=0.21,
                ),
                BuilderResponse(
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
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=2),
                    ),
                ),
                BuilderResponse(
                    response=SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=_create_bid(value=3),
                    ),
                ),
                BuilderResponse(
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
@pytest.mark.parametrize("builder_mocks", [3], indirect=True)
async def test_bid_selection_builders(
    builder_responses: list[BuilderResponse],
    expected_bid_total_value: int,
    beacon_chain: BeaconChain,
    multi_builder: MultiBuilder,
    builder_mocks: list[aiointercept],
) -> None:
    for builder in multi_builder.builders:
        builder._bid_request_auth_cache[(123, "0x9abc")] = (
            SchemaShared.SignedBuilderRequestAuth(
                message=SchemaShared.BuilderRequestAuth(data="0x", slot="123"),
                signature="0x" + "00" * 96,
            )
        )
    for server, builder_response in zip(builder_mocks, builder_responses, strict=True):
        url_regex_to_mock = re.compile(
            rf"{re.escape(server.server_url)}/eth/v1/builder/execution_payload_bid/.+",
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
        server.post(
            url=url_regex_to_mock,
            callback=_callback,
        )

    result = await multi_builder.get_execution_payload_bid(
        slot=123,
        parent_hash="0x" + "aa" * 32,
        parent_root="0x" + "bb" * 32,
        proposer_pubkey="0x9abc",
        fork_version=beacon_chain.current_fork_version,
        soft_timeout=0.1,
        hard_timeout=0.2,
    )
    if result is None:
        assert expected_bid_total_value is None
    else:
        builder, bid = result
        assert bid.total_value == expected_bid_total_value
