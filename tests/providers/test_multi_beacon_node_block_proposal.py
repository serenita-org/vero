"""These test the additional behavior of MultiBeaconNode (vs the simple BeaconNode)
when multiple beacon nodes are provided to it. That includes:
- requesting blocks from all beacon nodes and returning the best one
"""

import asyncio
import re
from functools import partial
from typing import Any, TypedDict

import pytest
from aiohttp.web_exceptions import HTTPRequestTimeout
from aiointercept import CallbackResult, aiointercept

from providers import BeaconChain, MultiBeaconNode
from providers._headers import (
    ETH_CONSENSUS_BLOCK_VALUE,
    ETH_CONSENSUS_VERSION,
    ETH_EXECUTION_PAYLOAD_INCLUDED,
    ETH_EXECUTION_PAYLOAD_VALUE,
    ContentType,
)
from schemas import SchemaBeaconAPI, SchemaShared


class BeaconNodeResponse(TypedDict):
    response: SchemaBeaconAPI.ProduceBlockV4Response | None
    exception: Exception | None
    delay: float | int


class BeaconNodeResponseSequence(TypedDict):
    node_name: str
    responses: list[BeaconNodeResponse]


@pytest.mark.parametrize(
    argnames=("bn_response_sequences", "best_bn_name", "returned_block_value"),
    argvalues=[
        pytest.param(
            [
                dict(
                    node_name="a",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV4Response(
                                version=SchemaShared.ForkVersion.GLOAS,
                                execution_payload_included=False,
                                execution_payload_value=str(100),
                                consensus_block_value=str(50),
                                builder_url=None,
                                data=b"",
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    node_name="b",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV4Response(
                                version=SchemaShared.ForkVersion.GLOAS,
                                execution_payload_included=False,
                                execution_payload_value=str(150),
                                consensus_block_value=str(50),
                                builder_url=None,
                                data=b"",
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    node_name="c",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV4Response(
                                version=SchemaShared.ForkVersion.GLOAS,
                                execution_payload_included=False,
                                execution_payload_value=str(120),
                                consensus_block_value=str(50),
                                builder_url=None,
                                data=b"",
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
            ],
            "b",
            200,
            id="Happy path - blocks returned from all beacon nodes",
        ),
        pytest.param(
            [
                dict(
                    node_name="a",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV4Response(
                                version=SchemaShared.ForkVersion.GLOAS,
                                execution_payload_included=False,
                                execution_payload_value=str(100),
                                consensus_block_value=str(50),
                                builder_url=None,
                                data=b"",
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    node_name="b",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV4Response(
                                version=SchemaShared.ForkVersion.GLOAS,
                                execution_payload_included=False,
                                execution_payload_value=str(150),
                                consensus_block_value=str(50),
                                builder_url=None,
                                data=b"",
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    node_name="c",
                    responses=[
                        BeaconNodeResponse(
                            response=None,
                            exception=HTTPRequestTimeout(),
                            delay=0,
                        ),
                    ],
                ),
            ],
            "b",
            200,
            id="2/3 blocks returned, 1 request timeout",
        ),
        pytest.param(
            [
                dict(
                    node_name="a",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV4Response(
                                version=SchemaShared.ForkVersion.GLOAS,
                                execution_payload_included=False,
                                execution_payload_value=str(100),
                                consensus_block_value=str(50),
                                builder_url=None,
                                data=b"",
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    node_name="b",
                    responses=[
                        BeaconNodeResponse(
                            response=None,
                            exception=HTTPRequestTimeout(),
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    node_name="c",
                    responses=[
                        BeaconNodeResponse(
                            response=None,
                            exception=HTTPRequestTimeout(),
                            delay=0,
                        ),
                    ],
                ),
            ],
            "a",
            150,
            id="1/3 blocks returned, 2 requests time out",
        ),
        pytest.param(
            [
                dict(
                    node_name="a",
                    responses=[
                        BeaconNodeResponse(
                            response=None,
                            exception=HTTPRequestTimeout(),
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    node_name="b",
                    responses=[
                        BeaconNodeResponse(
                            response=None,
                            exception=HTTPRequestTimeout(),
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    node_name="c",
                    responses=[
                        BeaconNodeResponse(
                            response=None,
                            exception=HTTPRequestTimeout(),
                            delay=0,
                        ),
                    ],
                ),
            ],
            "b",
            0,
            id="No blocks returned -> produce_best_block raises an Exception",
        ),
        pytest.param(
            [
                dict(
                    node_name="a",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV4Response(
                                version=SchemaShared.ForkVersion.GLOAS,
                                execution_payload_included=False,
                                execution_payload_value=str(150),
                                consensus_block_value=str(50),
                                builder_url=None,
                                data=b"",
                            ),
                            exception=None,
                            delay=0.05,
                        ),
                    ],
                ),
                dict(
                    node_name="b",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV4Response(
                                version=SchemaShared.ForkVersion.GLOAS,
                                execution_payload_included=False,
                                execution_payload_value=str(200),
                                consensus_block_value=str(50),
                                builder_url=None,
                                data=b"",
                            ),
                            exception=None,
                            delay=0.06,
                        ),
                    ],
                ),
                dict(
                    node_name="c",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV4Response(
                                version=SchemaShared.ForkVersion.GLOAS,
                                execution_payload_included=False,
                                execution_payload_value=str(1000),
                                consensus_block_value=str(500),
                                builder_url=None,
                                data=b"",
                            ),
                            exception=None,
                            delay=0.2,
                        ),
                    ],
                ),
            ],
            "b",
            250,
            id="2 fast responses and 1 delayed - we do not wait for the delayed one",
        ),
        pytest.param(
            [
                dict(
                    node_name="a",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV4Response(
                                version=SchemaShared.ForkVersion.GLOAS,
                                execution_payload_included=False,
                                execution_payload_value="",
                                consensus_block_value="",
                                builder_url=None,
                                data=b"",
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
            ],
            "a",
            0,
            # https://github.com/OffchainLabs/prysm/issues/15174
            id="No block value provided",
        ),
    ],
)
@pytest.mark.parametrize("beacon_node_mocks", [3], indirect=True)
async def test_produce_best_block(
    bn_response_sequences: list[BeaconNodeResponseSequence],
    best_bn_name: str,
    returned_block_value: int,
    multi_beacon_node: MultiBeaconNode,
    beacon_chain: BeaconChain,
    beacon_nodes_by_name: dict[str, aiointercept],
) -> None:
    """Tests that the multi-beacon requests blocks from all beacon nodes
    and returns the one with the highest value.
    """
    for sequence in bn_response_sequences:
        server = beacon_nodes_by_name[sequence["node_name"]]
        url_regex_to_mock = re.compile(
            rf"{re.escape(server.server_url)}/eth/v4/validator/blocks/\d+\?",
        )

        for r in sequence["responses"]:
            response, exception, delay = r["response"], r["exception"], r["delay"]

            async def _f(
                _response: SchemaBeaconAPI.ProduceBlockV4Response | None,
                _exception: Exception | None,
                _delay: float,
                *args: Any,
                **kwargs: Any,
            ) -> CallbackResult:
                await asyncio.sleep(_delay)
                if _exception:
                    raise _exception
                if _response:
                    return CallbackResult(
                        body=_response.data,
                        headers={
                            ETH_CONSENSUS_VERSION: _response.version.value.lower(),
                            ETH_EXECUTION_PAYLOAD_VALUE: _response.execution_payload_value,
                            ETH_CONSENSUS_BLOCK_VALUE: _response.consensus_block_value,
                            ETH_EXECUTION_PAYLOAD_INCLUDED: "false",
                        },
                    )
                raise ValueError("No exception or response to return")

            _callback = partial(
                _f,
                response,
                exception,
                delay,
            )
            server.post(
                url=url_regex_to_mock,
                callback=_callback,
            )

    success_expected = any(
        response["response"] is not None
        for sequence in bn_response_sequences
        for response in sequence["responses"]
    )

    if success_expected:
        (
            full_response,
            content_type,
            bn,
        ) = await multi_beacon_node._produce_best_block(
            slot=1,
            graffiti=b"test_produce_best_block",
            builder_config=SchemaBeaconAPI.BuilderConfig(
                min_bid="0",
                builder_boost_factor="90",
                builders=[],
            ),
            randao_reveal="randao",
            signed_payload_bid=None,
            fork_version=beacon_chain.current_fork_version,
            soft_timeout=0.1666,
        )
        assert content_type == ContentType.JSON
        assert str(bn.base_url) == beacon_nodes_by_name[best_bn_name].server_url
        assert (
            int(full_response.consensus_block_value)
            + int(full_response.execution_payload_value)
            == returned_block_value
        )
    else:
        with pytest.raises(
            expected_exception=RuntimeError,
            match="Failed to get a response from all beacon nodes",
        ):
            await multi_beacon_node._produce_best_block(
                slot=1,
                graffiti=b"test_produce_best_block",
                builder_config=SchemaBeaconAPI.BuilderConfig(
                    min_bid="0",
                    builder_boost_factor="90",
                    builders=[],
                ),
                randao_reveal="randao",
                signed_payload_bid=None,
                fork_version=beacon_chain.current_fork_version,
                soft_timeout=0.1666,
            )
