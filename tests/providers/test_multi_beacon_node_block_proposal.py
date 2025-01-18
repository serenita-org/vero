"""These test the additional behavior of MultiBeaconNode (vs the simple BeaconNode)
when multiple beacon nodes are provided to it. That includes:
- requesting blocks from all beacon nodes and returning the best one
"""

import asyncio
import re
from functools import partial
from typing import Any, TypedDict

import msgspec.json
import pytest
from aiohttp.web_exceptions import HTTPRequestTimeout
from aioresponses import CallbackResult, aioresponses

from providers import MultiBeaconNode
from schemas import SchemaBeaconAPI
from spec.block import BeaconBlockClass


class BeaconNodeResponse(TypedDict):
    response: SchemaBeaconAPI.ProduceBlockV3Response | None
    exception: Exception | None
    delay: float | int


class BeaconNodeResponseSequence(TypedDict):
    host: str
    responses: list[BeaconNodeResponse]


@pytest.mark.parametrize(
    argnames=("bn_response_sequences", "returned_block_value"),
    argvalues=[
        pytest.param(
            [
                dict(
                    host="beacon-node-a",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV3Response(
                                version=SchemaBeaconAPI.BeaconBlockVersion.DENEB,
                                execution_payload_blinded=False,
                                execution_payload_value=str(100),
                                consensus_block_value=str(50),
                                data=dict(),
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    host="beacon-node-b",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV3Response(
                                version=SchemaBeaconAPI.BeaconBlockVersion.DENEB,
                                execution_payload_blinded=False,
                                execution_payload_value=str(150),
                                consensus_block_value=str(50),
                                data=dict(),
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    host="beacon-node-c",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV3Response(
                                version=SchemaBeaconAPI.BeaconBlockVersion.DENEB,
                                execution_payload_blinded=False,
                                execution_payload_value=str(120),
                                consensus_block_value=str(50),
                                data=dict(),
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
            ],
            200,
            id="Happy path - blocks returned from all beacon nodes",
        ),
        pytest.param(
            [
                dict(
                    host="beacon-node-a",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV3Response(
                                version=SchemaBeaconAPI.BeaconBlockVersion.DENEB,
                                execution_payload_blinded=False,
                                execution_payload_value=str(100),
                                consensus_block_value=str(50),
                                data=dict(),
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    host="beacon-node-b",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV3Response(
                                version=SchemaBeaconAPI.BeaconBlockVersion.DENEB,
                                execution_payload_blinded=False,
                                execution_payload_value=str(150),
                                consensus_block_value=str(50),
                                data=dict(),
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    host="beacon-node-c",
                    responses=[
                        BeaconNodeResponse(
                            response=None,
                            exception=HTTPRequestTimeout(),
                            delay=0,
                        ),
                    ],
                ),
            ],
            200,
            id="2/3 blocks returned, 1 request timeout",
        ),
        pytest.param(
            [
                dict(
                    host="beacon-node-a",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV3Response(
                                version=SchemaBeaconAPI.BeaconBlockVersion.DENEB,
                                execution_payload_blinded=False,
                                execution_payload_value=str(100),
                                consensus_block_value=str(50),
                                data=dict(),
                            ),
                            exception=None,
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    host="beacon-node-b",
                    responses=[
                        BeaconNodeResponse(
                            response=None,
                            exception=HTTPRequestTimeout(),
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    host="beacon-node-c",
                    responses=[
                        BeaconNodeResponse(
                            response=None,
                            exception=HTTPRequestTimeout(),
                            delay=0,
                        ),
                    ],
                ),
            ],
            150,
            id="1/3 blocks returned, 2 requests time out",
        ),
        pytest.param(
            [
                dict(
                    host="beacon-node-a",
                    responses=[
                        BeaconNodeResponse(
                            response=None,
                            exception=HTTPRequestTimeout(),
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    host="beacon-node-b",
                    responses=[
                        BeaconNodeResponse(
                            response=None,
                            exception=HTTPRequestTimeout(),
                            delay=0,
                        ),
                    ],
                ),
                dict(
                    host="beacon-node-c",
                    responses=[
                        BeaconNodeResponse(
                            response=None,
                            exception=HTTPRequestTimeout(),
                            delay=0,
                        ),
                    ],
                ),
            ],
            0,
            id="No blocks returned -> produce_block_v3 raises an Exception",
        ),
        pytest.param(
            [
                dict(
                    host="beacon-node-a",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV3Response(
                                version=SchemaBeaconAPI.BeaconBlockVersion.DENEB,
                                execution_payload_blinded=False,
                                execution_payload_value=str(150),
                                consensus_block_value=str(50),
                                data=dict(),
                            ),
                            exception=None,
                            delay=0.05,
                        ),
                    ],
                ),
                dict(
                    host="beacon-node-b",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV3Response(
                                version=SchemaBeaconAPI.BeaconBlockVersion.DENEB,
                                execution_payload_blinded=False,
                                execution_payload_value=str(200),
                                consensus_block_value=str(50),
                                data=dict(),
                            ),
                            exception=None,
                            delay=0.06,
                        ),
                    ],
                ),
                dict(
                    host="beacon-node-c",
                    responses=[
                        BeaconNodeResponse(
                            response=SchemaBeaconAPI.ProduceBlockV3Response(
                                version=SchemaBeaconAPI.BeaconBlockVersion.DENEB,
                                execution_payload_blinded=False,
                                execution_payload_value=str(1000),
                                consensus_block_value=str(500),
                                data=dict(),
                            ),
                            exception=None,
                            delay=0.2,
                        ),
                    ],
                ),
            ],
            250,
            id="2 fast responses and 1 delayed - we do not wait for the delayed one",
        ),
    ],
)
@pytest.mark.usefixtures("_beacon_block_class_init")
async def test_produce_block_v3(
    bn_response_sequences: list[BeaconNodeResponseSequence],
    returned_block_value: int,
    multi_beacon_node_three_inited_nodes: MultiBeaconNode,
) -> None:
    """Tests that the multi-beacon requests blocks from all beacon nodes
    and returns the one with the highest value.
    """
    _empty_beacon_block = BeaconBlockClass.Deneb().to_obj()

    with aioresponses() as m:
        for sequence in bn_response_sequences:
            bn_host = sequence["host"]
            url_regex_to_mock = re.compile(
                rf"^http://{bn_host}:1234/eth/v3/validator/blocks/\d+",
            )

            for r in sequence["responses"]:
                response, exception, delay = r["response"], r["exception"], r["delay"]

                if response:
                    response.data["block"] = _empty_beacon_block

                async def _f(
                    _response: SchemaBeaconAPI.ProduceBlockV3Response | None,
                    _exception: Exception | None,
                    _delay: float,
                    *args: Any,
                    **kwargs: Any,
                ) -> CallbackResult:
                    await asyncio.sleep(_delay)
                    if _exception:
                        raise _exception
                    if _response:
                        return CallbackResult(body=msgspec.json.encode(_response))
                    raise ValueError("No exception or response to return")

                _callback = partial(
                    _f,
                    response,
                    exception,
                    delay,
                )
                m.get(
                    url=url_regex_to_mock,
                    callback=_callback,
                )

        success_expected = any(
            response["response"] is not None
            for sequence in bn_response_sequences
            for response in sequence["responses"]
        )

        if success_expected:
            result = await multi_beacon_node_three_inited_nodes.produce_block_v3(
                slot=1,
                graffiti=b"test_produce_block_v3",
                builder_boost_factor=90,
                randao_reveal="randao",
            )
            (
                block,
                full_response,
            ) = result
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
                await multi_beacon_node_three_inited_nodes.produce_block_v3(
                    slot=1,
                    graffiti=b"test_produce_block_v3",
                    builder_boost_factor=90,
                    randao_reveal="randao",
                )
