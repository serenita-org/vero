import asyncio
import logging
import time
from pathlib import Path

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
    ValidatorDutyService,
    ValidatorDutyServiceOptions,
    ValidatorStatusTrackerService,
)
from spec import SpecAttestation, SpecBeaconBlock, SpecSyncCommittee
from spec.base import SpecElectra
from spec.configs import get_network_spec
from tasks import TaskManager

_logger = logging.getLogger("vero-init")


async def _wait_for_genesis(genesis_timestamp: int) -> None:
    while True:
        time_remaining = genesis_timestamp - time.time()
        if time_remaining <= 0:
            break

        _logger.info(f"Waiting for genesis: {time_remaining:.2f}s remaining")
        await asyncio.sleep(min(time_remaining, 10))


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


def load_spec(cli_args: CLIArgs) -> SpecElectra:
    spec = get_network_spec(
        network=cli_args.network,
        network_custom_config_path=cli_args.network_custom_config_path,
    )
    # Dynamically create some of the SSZ classes
    SpecAttestation.initialize(spec=spec)
    SpecBeaconBlock.initialize(spec=spec)
    SpecSyncCommittee.initialize(spec=spec)

    return spec


async def run_services(
    cli_args: CLIArgs,
    task_manager: TaskManager,
    scheduler: AsyncIOScheduler,
    validator_duty_services: list[ValidatorDutyService],
    shutdown_event: asyncio.Event,
) -> None:
    spec = load_spec(cli_args=cli_args)

    beacon_chain = BeaconChain(
        spec=spec,
        task_manager=task_manager,
    )

    async with (
        RemoteSigner(url=cli_args.remote_signer_url) as remote_signer,
        MultiBeaconNode(
            beacon_node_urls=cli_args.beacon_node_urls,
            beacon_node_urls_proposal=cli_args.beacon_node_urls_proposal,
            spec=spec,
            scheduler=scheduler,
            task_manager=task_manager,
            cli_args=cli_args,
        ) as multi_beacon_node,
    ):
        beacon_chain.initialize(genesis=multi_beacon_node.best_beacon_node.genesis)
        await _wait_for_genesis(
            genesis_timestamp=beacon_chain.get_timestamp_for_slot(0)
        )
        beacon_chain.start_slot_ticker()

        _logger.info(f"Current epoch: {beacon_chain.current_epoch}")
        _logger.info(f"Current slot: {beacon_chain.current_slot}")

        validator_status_tracker_service = ValidatorStatusTrackerService(
            multi_beacon_node=multi_beacon_node,
            beacon_chain=beacon_chain,
            remote_signer=remote_signer,
            scheduler=scheduler,
            task_manager=task_manager,
        )
        await validator_status_tracker_service.initialize()
        beacon_chain.new_slot_handlers.append(
            validator_status_tracker_service.on_new_slot
        )
        _logger.info("Initialized validator status tracker")

        validator_service_args = ValidatorDutyServiceOptions(
            multi_beacon_node=multi_beacon_node,
            beacon_chain=beacon_chain,
            remote_signer=remote_signer,
            validator_status_tracker_service=validator_status_tracker_service,
            scheduler=scheduler,
            cli_args=cli_args,
            task_manager=task_manager,
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
            validator_duty_services.append(service)
            beacon_chain.new_slot_handlers.append(service.on_new_slot)
        _logger.info("Started validator duty services")

        event_consumer_service = EventConsumerService(
            multi_beacon_node=multi_beacon_node,
            beacon_chain=beacon_chain,
            scheduler=scheduler,
            task_manager=task_manager,
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
        await monitor_event_loop(
            beacon_chain=beacon_chain, shutdown_event=shutdown_event
        )
