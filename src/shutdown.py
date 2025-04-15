import asyncio
import logging
import signal

from services import BlockProposalService, ValidatorDutyService
from tasks import TaskManager

_logger = logging.getLogger("vero-shutdown")


async def shut_down(
    validator_duty_services: list[ValidatorDutyService], shutdown_event: asyncio.Event
) -> None:
    # Wait for ongoing/upcoming validator duties to be completed
    # before shutting down
    block_proposal_service = next(
        s for s in validator_duty_services if isinstance(s, BlockProposalService)
    )
    beacon_chain = block_proposal_service.beacon_chain

    # Wait until there are no upcoming block proposal duties
    while block_proposal_service.has_upcoming_duty():
        duty_slot = block_proposal_service.next_duty_slot
        if duty_slot is None:
            break

        _logger.info(
            f"Waiting for upcoming block proposal to complete during slot {duty_slot}"
        )

        while beacon_chain.current_slot < duty_slot:
            _logger.info(f"Waiting for block proposal duty slot ({duty_slot}) to start")
            await beacon_chain.wait_for_next_slot()

        await block_proposal_service.wait_for_duty_completion()

    # Wait for all duties for the next slot to be complete
    _logger.info("Waiting for next slot to start")
    await beacon_chain.wait_for_next_slot()
    _logger.info("Waiting for duty completion")
    wait_tasks = [
        asyncio.create_task(s.wait_for_duty_completion())
        for s in validator_duty_services
    ]
    await asyncio.gather(*wait_tasks)

    _logger.info("Shutting down...")
    shutdown_event.set()


def shutdown_handler(
    signo: int,
    validator_duty_services: list[ValidatorDutyService],
    shutdown_event: asyncio.Event,
    task_manager: TaskManager,
) -> None:
    _logger.info(f"Received shutdown signal {signal.Signals(signo).name}")
    task_manager.submit_task(
        shut_down(
            validator_duty_services=validator_duty_services,
            shutdown_event=shutdown_event,
        )
    )
