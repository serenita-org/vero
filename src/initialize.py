import asyncio
import contextlib
import logging
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from observability.event_loop import monitor_event_loop
from providers import (
    DB,
    BeaconChain,
    DoppelgangerDetector,
    DutyCache,
    Keymanager,
    MultiBeaconNode,
    RemoteSigner,
)
from providers.doppelganger_detector import DoppelgangersDetected
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
from spec.configs import get_network_spec

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from args import CLIArgs
    from spec.base import SpecFulu
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
        event_consumer_service.add_head_event_handler(
            event_handler=head_handler_service.handle_head_event,
        )

    for reorg_handler_service in (
        attestation_service,
        block_proposal_service,
        sync_committee_service,
    ):
        event_consumer_service.add_reorg_event_handler(
            event_handler=reorg_handler_service.handle_reorg_event,
        )

    event_consumer_service.add_slashing_event_handler(
        event_handler=validator_status_tracker_service.handle_slashing_event,
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


def load_spec(cli_args: CLIArgs) -> SpecFulu:
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

    async with contextlib.AsyncExitStack() as exit_stack:
        db = exit_stack.enter_context(DB(data_dir=cli_args.data_dir))
        db.run_migrations()

        multi_beacon_node = await exit_stack.enter_async_context(
            MultiBeaconNode(
                beacon_node_urls=cli_args.beacon_node_urls,
                beacon_node_urls_proposal=cli_args.beacon_node_urls_proposal,
                spec=spec,
                scheduler=scheduler,
                task_manager=task_manager,
                cli_args=cli_args,
            )
        )

        beacon_chain = BeaconChain(
            spec=spec,
            genesis=multi_beacon_node.best_beacon_node.genesis,
            task_manager=task_manager,
        )
        await _wait_for_genesis(
            genesis_timestamp=beacon_chain.get_timestamp_for_slot(0)
        )

        process_pool_executor = ProcessPoolExecutor()
        keymanager = Keymanager(
            db=db,
            beacon_chain=beacon_chain,
            multi_beacon_node=multi_beacon_node,
            cli_args=cli_args,
            process_pool_executor=process_pool_executor,
        )
        signature_provider: Keymanager | RemoteSigner
        if cli_args.enable_keymanager_api:
            signature_provider = await exit_stack.enter_async_context(keymanager)
        else:
            if cli_args.remote_signer_url is None:
                raise RuntimeError(
                    "remote_signer_url is None despite disabled Keymanager API"
                )
            signature_provider = await exit_stack.enter_async_context(
                RemoteSigner(
                    url=cli_args.remote_signer_url,
                    process_pool_executor=process_pool_executor,
                )
            )

        _logger.info(f"Current epoch: {beacon_chain.current_epoch}")
        _logger.info(f"Current slot: {beacon_chain.current_slot}")
        beacon_chain.start_slot_ticker()

        validator_status_tracker_service = ValidatorStatusTrackerService(
            multi_beacon_node=multi_beacon_node,
            beacon_chain=beacon_chain,
            signature_provider=signature_provider,
            scheduler=scheduler,
            task_manager=task_manager,
        )
        await validator_status_tracker_service.initialize()
        beacon_chain.new_slot_handlers.append(
            validator_status_tracker_service.on_new_slot
        )
        _logger.info("Initialized validator status tracker")

        if cli_args.enable_doppelganger_detection:
            try:
                await DoppelgangerDetector(
                    beacon_chain=beacon_chain,
                    beacon_node=multi_beacon_node.best_beacon_node,
                    validator_status_tracker_service=validator_status_tracker_service,
                ).detect()
            except DoppelgangersDetected:
                shutdown_event.set()
                raise

        validator_service_args = ValidatorDutyServiceOptions(
            multi_beacon_node=multi_beacon_node,
            beacon_chain=beacon_chain,
            signature_provider=signature_provider,
            keymanager=keymanager,
            duty_cache=DutyCache(data_dir=cli_args.data_dir),
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
            await exit_stack.enter_async_context(service)
            validator_duty_services.append(service)
            beacon_chain.new_slot_handlers.append(service.on_new_slot)
        _logger.info("Started validator duty services")

        event_consumer_service = EventConsumerService(
            beacon_nodes=multi_beacon_node.beacon_nodes,
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

        # Reaching this point means the shutdown_event was set
        # -> cancel all pending tasks
        task_manager.cancel_all()
