import asyncio
import datetime
import logging
from pathlib import Path

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs
from observability.event_loop import monitor_event_loop
from providers import BeaconChain, MultiBeaconNode, RemoteSigner
from schemas import SchemaBeaconAPI
from services import (
    AttestationService,
    BlockProposalService,
    EventConsumerService,
    SyncCommitteeService,
    ValidatorDutyServiceOptions,
    ValidatorStatusTrackerService,
)

_logger = logging.getLogger("vero-init")


async def _wait_for_genesis(genesis_datetime: datetime.datetime) -> None:
    # Waits for genesis to occur
    time_to_genesis = genesis_datetime - datetime.datetime.now(tz=pytz.UTC)
    while time_to_genesis.total_seconds() > 0:
        _logger.info(f"Waiting for genesis - {time_to_genesis} remaining")
        await asyncio.sleep(min(time_to_genesis.total_seconds(), 10))
        time_to_genesis = genesis_datetime - datetime.datetime.now(tz=pytz.UTC)


def _register_event_handlers(
    attestation_service: AttestationService,
    block_proposal_service: BlockProposalService,
    sync_committee_service: SyncCommitteeService,
    event_consumer_service: EventConsumerService,
    validator_status_tracker_service: ValidatorStatusTrackerService,
) -> None:
    # Add event handlers for head events, chain reorgs and slashing events
    for head_handler_service in (
        attestation_service,
        block_proposal_service,
        sync_committee_service,
    ):
        event_consumer_service.add_event_handler(
            event_handler=head_handler_service.handle_head_event,
            event_type=SchemaBeaconAPI.HeadEvent,
        )

    for reorg_handler_service in (
        attestation_service,
        block_proposal_service,
        sync_committee_service,
    ):
        event_consumer_service.add_event_handler(
            event_handler=reorg_handler_service.handle_reorg_event,
            event_type=SchemaBeaconAPI.ChainReorgEvent,
        )

    for event_type in (
        SchemaBeaconAPI.AttesterSlashingEvent,
        SchemaBeaconAPI.ProposerSlashingEvent,
    ):
        event_consumer_service.add_event_handler(
            event_handler=validator_status_tracker_service.handle_slashing_event,
            event_type=event_type,
        )


def check_data_dir_permissions(data_dir: Path) -> None:
    if not Path.is_dir(data_dir):
        _logger.info("Data directory does not exist, attempting to create it")
        try:
            Path.mkdir(data_dir, parents=True)
        except Exception as e:
            raise RuntimeError(
                f"Failed to create data directory at {data_dir}",
            ) from e

    # Attempt to write a file and reading from it
    test_filename = ".vero_test_permissions"
    test_file_path = data_dir / test_filename
    test_file_content = "test_permissions"
    with Path.open(test_file_path, "w") as f:
        f.write(test_file_content)
    with Path.open(test_file_path) as f:
        content_read = f.read()
    Path.unlink(test_file_path)
    if content_read != test_file_content:
        raise PermissionError(
            f"Mismatch between data written {test_file_content} and read {content_read} into test file",
        )


async def run_services(cli_args: CLIArgs) -> None:
    scheduler = AsyncIOScheduler(
        timezone=pytz.UTC,
        job_defaults=dict(misfire_grace_time=None),
    )
    scheduler.start()

    async with (
        RemoteSigner(url=cli_args.remote_signer_url) as remote_signer,
        MultiBeaconNode(
            beacon_node_urls=cli_args.beacon_node_urls,
            beacon_node_urls_proposal=cli_args.beacon_node_urls_proposal,
            scheduler=scheduler,
        ) as multi_beacon_node,
    ):
        beacon_chain = BeaconChain(multi_beacon_node=multi_beacon_node)

        await _wait_for_genesis(genesis_datetime=beacon_chain.get_datetime_for_slot(0))

        _logger.info(f"Current slot: {beacon_chain.current_slot}")
        _logger.info(f"Current epoch: {beacon_chain.current_epoch}")

        validator_status_tracker_service = ValidatorStatusTrackerService(
            multi_beacon_node=multi_beacon_node,
            beacon_chain=beacon_chain,
            remote_signer=remote_signer,
            scheduler=scheduler,
        )
        await validator_status_tracker_service.initialize()
        _logger.info("Initialized validator status tracker")

        validator_service_args = ValidatorDutyServiceOptions(
            multi_beacon_node=multi_beacon_node,
            beacon_chain=beacon_chain,
            remote_signer=remote_signer,
            validator_status_tracker_service=validator_status_tracker_service,
            scheduler=scheduler,
            cli_args=cli_args,
        )

        attestation_service = AttestationService(**validator_service_args)
        block_proposal_service = BlockProposalService(**validator_service_args)
        sync_committee_service = SyncCommitteeService(**validator_service_args)

        for service in (
            attestation_service,
            block_proposal_service,
            sync_committee_service,
        ):
            service.start()
        _logger.info("Started validator duty services")

        event_consumer_service = EventConsumerService(
            multi_beacon_node=multi_beacon_node,
            scheduler=scheduler,
        )

        _register_event_handlers(
            attestation_service=attestation_service,
            block_proposal_service=block_proposal_service,
            sync_committee_service=sync_committee_service,
            event_consumer_service=event_consumer_service,
            validator_status_tracker_service=validator_status_tracker_service,
        )
        _logger.info("Starting event consumer")
        event_consumer_service.start()

        # Run forever while monitoring the event loop
        await monitor_event_loop(beacon_chain=beacon_chain)
