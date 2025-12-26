import asyncio
import contextlib
import logging
import time
from pathlib import Path

from observability.event_loop import monitor_event_loop
from providers import (
    DB,
    DoppelgangerDetector,
    DutyCache,
    Keymanager,
    MultiBeaconNode,
    RemoteSigner,
    Vero,
)
from providers.doppelganger_detector import DoppelgangersDetected
from services import (
    AttestationService,
    BlockProposalService,
    EventConsumerService,
    SyncCommitteeService,
    ValidatorDutyServiceOptions,
    ValidatorStatusTrackerService,
)

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


async def run_services(vero: Vero) -> None:
    vero.scheduler.start()

    async with contextlib.AsyncExitStack() as exit_stack:
        db = exit_stack.enter_context(DB(data_dir=vero.cli_args.data_dir))
        db.run_migrations()

        multi_beacon_node = await exit_stack.enter_async_context(
            MultiBeaconNode(vero=vero)
        )

        await _wait_for_genesis(
            genesis_timestamp=vero.beacon_chain.get_timestamp_for_slot(0)
        )

        keymanager = Keymanager(
            db=db,
            multi_beacon_node=multi_beacon_node,
            vero=vero,
        )
        signature_provider: Keymanager | RemoteSigner
        if vero.cli_args.enable_keymanager_api:
            signature_provider = await exit_stack.enter_async_context(keymanager)
        else:
            if vero.cli_args.remote_signer_url is None:
                raise RuntimeError(
                    "remote_signer_url is None despite disabled Keymanager API"
                )
            signature_provider = await exit_stack.enter_async_context(
                RemoteSigner(
                    url=vero.cli_args.remote_signer_url,
                    vero=vero,
                )
            )

        _logger.info(f"Current epoch: {vero.beacon_chain.current_epoch}")
        _logger.info(f"Current slot: {vero.beacon_chain.current_slot}")
        vero.beacon_chain.start_slot_ticker()

        validator_status_tracker_service = ValidatorStatusTrackerService(
            multi_beacon_node=multi_beacon_node,
            signature_provider=signature_provider,
            vero=vero,
        )
        await validator_status_tracker_service.initialize()
        vero.beacon_chain.new_slot_handlers.append(
            validator_status_tracker_service.on_new_slot
        )
        _logger.info("Initialized validator status tracker")

        if vero.cli_args.enable_doppelganger_detection:
            try:
                await DoppelgangerDetector(
                    beacon_chain=vero.beacon_chain,
                    beacon_node=multi_beacon_node.best_beacon_node,
                    validator_status_tracker_service=validator_status_tracker_service,
                ).detect()
            except DoppelgangersDetected:
                vero.shutdown_event.set()
                raise

        validator_service_args = ValidatorDutyServiceOptions(
            multi_beacon_node=multi_beacon_node,
            signature_provider=signature_provider,
            keymanager=keymanager,
            duty_cache=DutyCache(data_dir=vero.cli_args.data_dir),
            validator_status_tracker_service=validator_status_tracker_service,
            vero=vero,
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
            vero.validator_duty_services.append(service)
            vero.beacon_chain.new_slot_handlers.append(service.on_new_slot)
        _logger.info("Started validator duty services")

        event_consumer_service = EventConsumerService(
            beacon_nodes=multi_beacon_node.beacon_nodes,
            vero=vero,
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
            beacon_chain=vero.beacon_chain,
            metrics=vero.metrics,
            shutdown_event=vero.shutdown_event,
        )

        # Reaching this point means the shutdown_event was set
        # -> cancel all pending tasks
        vero.task_manager.cancel_all()
