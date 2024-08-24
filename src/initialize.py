import asyncio
import datetime
import logging
import os
from pathlib import Path

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs
from observability.event_loop import EVENT_LOOP_LAG, EVENT_LOOP_TASKS
from providers import RemoteSigner, MultiBeaconNode, BeaconChain
from schemas import SchemaBeaconAPI
from services import (
    AttestationService,
    BlockProposalService,
    SyncCommitteeService,
    EventConsumerService,
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
            event_types=[SchemaBeaconAPI.HeadEvent],
        )

    for reorg_handler_service in (
        attestation_service,
        block_proposal_service,
        sync_committee_service,
    ):
        event_consumer_service.add_event_handler(
            event_handler=reorg_handler_service.handle_reorg_event,
            event_types=[SchemaBeaconAPI.ChainReorgEvent],
        )

    event_consumer_service.add_event_handler(
        event_handler=validator_status_tracker_service.handle_slashing_event,
        event_types=[
            SchemaBeaconAPI.AttesterSlashingEvent,
            SchemaBeaconAPI.ProposerSlashingEvent,
        ],
    )


def check_data_dir_permissions(cli_args: CLIArgs) -> None:
    if not os.path.isdir(cli_args.data_dir):
        _logger.info("Data directory does not exist, attempting to create it")
        try:
            os.makedirs(cli_args.data_dir)
        except Exception as e:
            raise RuntimeError(
                f"Failed to create data directory: {cli_args.data_dir} - {e}"
            )

    # Attempt to write a file and reading from it
    try:
        test_filename = ".vero_test_permissions"
        test_file_path = Path(cli_args.data_dir) / test_filename
        test_file_content = "test_permissions"
        with open(test_file_path, "w") as f:
            f.write(test_file_content)
        with open(test_file_path, "r") as f:
            content_read = f.read()
        os.remove(test_file_path)
        if content_read != test_file_content:
            raise PermissionError(
                f"Mismatch between data written {test_file_content} and read {content_read} into test file"
            )
    except Exception:
        raise


async def run_services(cli_args: CLIArgs) -> None:
    scheduler = AsyncIOScheduler(
        timezone=pytz.UTC, job_defaults=dict(misfire_grace_time=1)
    )
    scheduler.start()

    async with RemoteSigner(
        url=cli_args.remote_signer_url
    ) as remote_signer, MultiBeaconNode(
        beacon_node_urls=cli_args.beacon_node_urls,
        beacon_node_urls_proposal=cli_args.beacon_node_urls_proposal,
        scheduler=scheduler,
    ) as multi_beacon_node:
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

        validator_service_args = dict(
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

        scheduler.add_job(event_consumer_service.handle_events)
        _logger.info("Started event consumer")

        event_loop = asyncio.get_event_loop()
        _start = event_loop.time()
        _interval = 1

        while True:
            await asyncio.sleep(_interval)
            EVENT_LOOP_LAG.observe(event_loop.time() - _start - _interval)
            EVENT_LOOP_TASKS.set(len(asyncio.all_tasks(event_loop)))
            _start = event_loop.time()
