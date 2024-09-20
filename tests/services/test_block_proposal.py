import asyncio
import datetime

import pytest
import pytz
from pydantic import HttpUrl

from providers import BeaconChain
from schemas import SchemaBeaconAPI
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
    await block_proposal_service._prepare_beacon_proposer()


async def test_register_validators(
    block_proposal_service: BlockProposalService,
) -> None:
    # This test just checks that no exception is thrown
    await block_proposal_service._register_validators()


@pytest.mark.parametrize(
    "execution_payload_blinded",
    [pytest.param(False, id="Unblinded"), pytest.param(True, id="Blinded")],
    indirect=True,
)
async def test_publish_block(
    block_proposal_service: BlockProposalService,
    beacon_chain: BeaconChain,
    random_active_validator: ValidatorIndexPubkey,
    execution_payload_blinded: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Populate the service with a proposal duty
    duty_slot = beacon_chain.current_slot + 1

    block_proposal_service.proposer_duties[
        duty_slot // beacon_chain.spec.SLOTS_PER_EPOCH
    ].add(
        SchemaBeaconAPI.ProposerDuty(
            pubkey=random_active_validator.pubkey,
            validator_index=random_active_validator.index,
            slot=duty_slot,
        ),
    )

    # Wait for duty slot
    time_to_slot = datetime.datetime.now(
        tz=pytz.UTC,
    ) - beacon_chain.get_datetime_for_slot(duty_slot)
    await asyncio.sleep(time_to_slot.total_seconds())

    blocks_published_before = _VC_PUBLISHED_BLOCKS._value.get()

    await block_proposal_service.propose_block(slot=duty_slot)

    assert any("Published block" in m for m in caplog.messages)
    assert _VC_PUBLISHED_BLOCKS._value.get() == blocks_published_before + 1


@pytest.mark.parametrize(
    "beacon_node_urls_proposal",
    [
        pytest.param([], id="No proposal beacon nodes specified"),
        pytest.param(
            [
                HttpUrl("http://beacon-node-proposal-1:1234"),
                HttpUrl("http://beacon-node-proposal-2:1234"),
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
    beacon_node_urls_proposal: list[HttpUrl],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The provided proposal beacon node URLs should be exclusively used for block proposals,
    if specified.
    """
    # Populate the service with a proposal duty
    duty_slot = beacon_chain.current_slot + 1

    block_proposal_service.proposer_duties[
        duty_slot // beacon_chain.spec.SLOTS_PER_EPOCH
    ].add(
        SchemaBeaconAPI.ProposerDuty(
            pubkey=random_active_validator.pubkey,
            validator_index=random_active_validator.index,
            slot=duty_slot,
        ),
    )

    # Wait for duty slot
    time_to_slot = datetime.datetime.now(
        tz=pytz.UTC,
    ) - beacon_chain.get_datetime_for_slot(duty_slot)
    await asyncio.sleep(time_to_slot.total_seconds())

    await block_proposal_service.propose_block(slot=duty_slot)

    _override_log_string = "Overriding beacon nodes for block proposal"
    if len(beacon_node_urls_proposal) > 0:
        assert any(_override_log_string in m for m in caplog.messages)
    else:
        assert all(_override_log_string not in m for m in caplog.messages)
