import pytest
from aiointercept import aiointercept
from yarl import URL

from providers import MultiBeaconNode
from schemas.shared import Fork
from spec import initialize_preset, preset_types
from spec.base import SpecGloas
from tests.ssz_objects import ZERO_ROOT, ZERO_SIGNATURE, attestation_data_obj, bitvector


# Vero uses both the participant count and bitlist length to choose an aggregate.
# At eight bits, the SSZ delimiter is in a separate byte and must be excluded.
@pytest.mark.parametrize("fork", [Fork.FULU, Fork.GLOAS], indirect=True)
async def test_get_aggregate_attestation_with_byte_aligned_bitlist(
    multi_beacon_node: MultiBeaconNode,
    beacon_node_mocks: list[aiointercept],
    spec: SpecGloas,
    fork: Fork,
) -> None:
    beacon_mock = beacon_node_mocks[0]
    url = URL(f"{beacon_mock.server_url}/eth/v2/validator/aggregate_attestation")
    beacon_mock.get(
        url.with_query(attestation_data_root=ZERO_ROOT, slot=123, committee_index=14),
        payload={
            "version": fork.value,
            "data": {
                # Two participants in eight positions, followed by the delimiter byte.
                "aggregation_bits": "0x8101",
                "committee_bits": bitvector(
                    spec.MAX_COMMITTEES_PER_SLOT, [False] * 14 + [True]
                ),
                "data": attestation_data_obj(slot="123"),
                "signature": ZERO_SIGNATURE,
            },
        },
    )

    aggregate = await multi_beacon_node.get_aggregate_attestation_v2(
        attestation_data_root=ZERO_ROOT, slot=123, committee_index=14
    )

    assert aggregate.aggregation_bits == (
        True,
        False,
        False,
        False,
        False,
        False,
        False,
        True,
    )
    assert [index for index, bit in enumerate(aggregate.committee_bits) if bit] == [14]


# Minimal uses an eight-bit sync subcommittee vector. A hard-coded mainnet codec
# would reject this valid one-byte Beacon API response.
async def test_get_sync_committee_contribution_with_minimal_preset(
    multi_beacon_node: MultiBeaconNode,
    beacon_node_mocks: list[aiointercept],
) -> None:
    beacon_mock = beacon_node_mocks[0]
    url = URL(f"{beacon_mock.server_url}/eth/v1/validator/sync_committee_contribution")
    beacon_mock.get(
        url.with_query(slot=123, subcommittee_index=1, beacon_block_root=ZERO_ROOT),
        payload={
            "data": {
                "slot": "123",
                "beacon_block_root": ZERO_ROOT,
                "subcommittee_index": "1",
                "aggregation_bits": "0x85",
                "signature": ZERO_SIGNATURE,
            },
        },
    )

    previous_preset = preset_types().preset
    try:
        initialize_preset("minimal")
        contribution = await multi_beacon_node.get_sync_committee_contribution(
            slot=123, subcommittee_index=1, beacon_block_root=ZERO_ROOT
        )
        assert contribution.aggregation_bits == (
            True,
            False,
            True,
            False,
            False,
            False,
            False,
            True,
        )
    finally:
        initialize_preset(previous_preset)
