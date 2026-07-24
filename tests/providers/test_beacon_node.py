import contextlib
import re
from copy import copy

import msgspec
import pytest
from aiohttp.hdrs import CONTENT_TYPE
from aioresponses import CallbackResult, aioresponses

from providers import BeaconNode, MultiBeaconNode, Vero
from providers._headers import ContentType
from schemas import SchemaBeaconAPI
from spec.base import Version
from spec.common import UInt64SerializedAsString
from tests.ssz_objects import ZERO_SIGNATURE, make_block


@pytest.mark.parametrize(
    "response_content_type",
    [ContentType.JSON, ContentType.OCTET_STREAM],
)
async def test_produce_block_v3_response(
    response_content_type: ContentType,
    vero: Vero,
) -> None:
    block = make_block(slot=1, blinded=False)
    block_data = (
        block.to_json() if response_content_type == ContentType.JSON else block.to_ssz()
    )
    api_response = SchemaBeaconAPI.ProduceBlockV3Response(
        version=SchemaBeaconAPI.ForkVersion.FULU,
        # Use different values here vs headers below
        # to test that Vero considers the header
        # values as the source of truth
        execution_payload_blinded=True,
        execution_payload_value="1",
        consensus_block_value="2",
        data=block_data,
    )
    response_body = (
        msgspec.json.encode(
            {
                "version": api_response.version,
                "execution_payload_blinded": api_response.execution_payload_blinded,
                "execution_payload_value": api_response.execution_payload_value,
                "consensus_block_value": api_response.consensus_block_value,
                "data": msgspec.Raw(block_data),
            }
        )
        if response_content_type == ContentType.JSON
        else block_data
    )
    if response_content_type == ContentType.JSON:
        assert b'"content_type"' not in response_body

    response_headers = {
        CONTENT_TYPE: response_content_type.value,
        "Eth-Consensus-Version": api_response.version.value,
        "Eth-Execution-Payload-Blinded": "false",
        "Eth-Execution-Payload-Value": "3",
        "Eth-Consensus-Block-Value": "4",
    }

    with aioresponses() as mocked_responses:
        mocked_responses.get(
            re.compile(r"http://beacon-node-a:1234/eth/v3/validator/blocks/1.*"),
            body=response_body,
            headers=response_headers,
        )
        beacon_node = BeaconNode(
            base_url="http://beacon-node-a:1234",
            vero=vero,
        )
        beacon_node._force_json_wire_format = response_content_type == ContentType.JSON
        try:
            response, content_type = await beacon_node.produce_block_v3(
                slot=1,
                graffiti=b"",
                builder_boost_factor=90,
                randao_reveal=ZERO_SIGNATURE,
            )
        finally:
            await beacon_node.client_session.close()

    assert response.version == api_response.version
    assert response.execution_payload_blinded is False
    assert response.execution_payload_value == "3"
    assert response.consensus_block_value == "4"
    assert response.data is response_body
    assert content_type == response_content_type
    parsed_block = MultiBeaconNode._parse_block_response(response, content_type)
    assert parsed_block.block.slot == 1


@pytest.mark.parametrize(
    "spec_mismatch",
    [
        pytest.param(False, id="match"),
        pytest.param(True, id="mismatch"),
    ],
)
@pytest.mark.parametrize(
    argnames="cli_args",
    argvalues=[
        pytest.param(
            {
                "ignore_spec_mismatch": False,
            },
            id="spec mismatch not ignored",
        ),
        pytest.param(
            {
                "ignore_spec_mismatch": True,
            },
            id="spec mismatch ignored",
        ),
    ],
    indirect=["cli_args"],
)
async def test_initialize_spec_mismatch(
    spec_mismatch: bool,
    vero: Vero,
) -> None:
    """The BeaconNode should fail to initialize on a spec mismatch."""
    with contextlib.ExitStack() as stack:
        m = stack.enter_context(aioresponses())

        spec_to_return = vero.spec
        if spec_mismatch:
            spec_to_return = copy(vero.spec)
            spec_to_return.SLOTS_PER_EPOCH = UInt64SerializedAsString(5)
            spec_to_return.ELECTRA_FORK_VERSION = Version("0x00abcdef")

        m.get(
            url=re.compile(r"http://beacon-node-\w:1234/eth/v1/config/spec"),
            callback=lambda *args, **kwargs: CallbackResult(
                payload=dict(data=spec_to_return.to_obj()),
            ),
        )

        bn = BeaconNode(
            base_url="http://beacon-node-a:1234",
            vero=vero,
        )
        if not spec_mismatch or vero.cli_args.ignore_spec_mismatch:
            # No mismatch, or mismatch explicitly ignored -> init should not raise
            await bn._initialize_full()
            assert bn.initialized is True
        else:
            with pytest.raises(
                ValueError,
                match=re.escape(
                    "Spec values returned by beacon node beacon-node-a not equal to hardcoded spec values. Use the `--ignore-spec-mismatch` flag to ignore this error."
                ),
            ):
                await bn._initialize_full()

        await bn.client_session.close()
