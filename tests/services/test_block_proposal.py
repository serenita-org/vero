import asyncio

import pytest

from providers import BeaconChain
from providers.beacon_node import ContentType
from schemas import SchemaBeaconAPI
from schemas.beacon_api import ForkVersion
from schemas.validator import ValidatorIndexPubkey
from services import BlockProposalService
from services.block_proposal import _VC_PUBLISHED_BLOCKS


async def test_update_duties(
    block_proposal_service: BlockProposalService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # This test just checks that no exception is thrown
    assert len(block_proposal_service.proposer_duties) == 0
    await block_proposal_service._update_duties()
    assert any("Updated duties" in m for m in caplog.messages)
    assert len(block_proposal_service.proposer_duties) > 0


async def test_prepare_beacon_proposer(
    block_proposal_service: BlockProposalService,
) -> None:
    # This test just checks that no exception is thrown
    await block_proposal_service.prepare_beacon_proposer()


async def test_register_validators(
    block_proposal_service: BlockProposalService,
    beacon_chain: BeaconChain,
) -> None:
    # This test just checks that no exception is thrown
    await block_proposal_service.register_validators(
        current_slot=beacon_chain.current_slot
    )


@pytest.mark.parametrize(
    "execution_payload_blinded",
    [pytest.param(False, id="Unblinded"), pytest.param(True, id="Blinded")],
    indirect=True,
)
@pytest.mark.parametrize(
    "response_content_type",
    [
        pytest.param(ContentType.JSON, id="JSON"),
        pytest.param(ContentType.OCTET_STREAM, id="SSZ"),
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    "fork_version",
    [
        pytest.param(ForkVersion.DENEB, id="Deneb"),
        pytest.param(ForkVersion.ELECTRA, id="Electra"),
    ],
    indirect=True,
)
async def test_publish_block(
    block_proposal_service: BlockProposalService,
    beacon_chain: BeaconChain,
    random_active_validator: ValidatorIndexPubkey,
    execution_payload_blinded: bool,
    response_content_type: ContentType,
    fork_version: ForkVersion,
    caplog: pytest.LogCaptureFixture,
) -> None:
    if response_content_type == ContentType.OCTET_STREAM:
        pytest.skip("SSZ not supported yet")

    # Populate the service with a proposal duty
    duty_slot = beacon_chain.current_slot + 1

    block_proposal_service.proposer_duties[
        duty_slot // beacon_chain.SLOTS_PER_EPOCH
    ].add(
        SchemaBeaconAPI.ProposerDuty(
            pubkey=random_active_validator.pubkey,
            validator_index=str(random_active_validator.index),
            slot=str(duty_slot),
        ),
    )
    block_proposal_service._last_slot_duty_started_for = 0
    block_proposal_service._last_slot_duty_completed_for = 0

    blocks_published_before = _VC_PUBLISHED_BLOCKS._value.get()

    # Wait for duty slot
    await asyncio.sleep(max(0.0, -beacon_chain.time_since_slot_start(duty_slot)))

    await block_proposal_service.propose_block(slot=duty_slot)

    assert any("Published block" in m for m in caplog.messages)
    assert _VC_PUBLISHED_BLOCKS._value.get() == blocks_published_before + 1
    assert block_proposal_service._last_slot_duty_started_for == duty_slot
    assert block_proposal_service._last_slot_duty_completed_for == duty_slot


@pytest.mark.parametrize(
    "beacon_node_urls_proposal",
    [
        pytest.param([], id="No proposal beacon nodes specified"),
        pytest.param(
            [
                "http://beacon-node-proposal-1:1234",
                "http://beacon-node-proposal-2:1234",
            ],
            id="Beacon nodes explicitly specified for block proposals",
        ),
    ],
    indirect=True,
)
async def test_block_proposal_beacon_node_urls_proposal(
    block_proposal_service: BlockProposalService,
    beacon_chain: BeaconChain,
    random_active_validator: ValidatorIndexPubkey,
    beacon_node_urls_proposal: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The provided proposal beacon node URLs should be exclusively used for block proposals,
    if specified.
    """
    # Populate the service with a proposal duty
    duty_slot = beacon_chain.current_slot + 1

    block_proposal_service.proposer_duties[
        duty_slot // beacon_chain.SLOTS_PER_EPOCH
    ].add(
        SchemaBeaconAPI.ProposerDuty(
            pubkey=random_active_validator.pubkey,
            validator_index=str(random_active_validator.index),
            slot=str(duty_slot),
        ),
    )

    # Wait for duty slot
    await asyncio.sleep(max(0.0, -beacon_chain.time_since_slot_start(duty_slot)))
    await block_proposal_service.propose_block(slot=duty_slot)

    _override_log_string = "Overriding beacon nodes for block proposal"
    if len(beacon_node_urls_proposal) > 0:
        assert any(_override_log_string in m for m in caplog.messages)
    else:
        assert all(_override_log_string not in m for m in caplog.messages)
