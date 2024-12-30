import asyncio
import logging
import signal

from services import ValidatorDutyService

_logger = logging.getLogger("vero-shutdown")


async def shut_down(
    validator_duty_services: list[ValidatorDutyService], shutdown_event: asyncio.Event
) -> None:
    # Wait for ongoing/upcoming validator duties to be completed
    services_with_upcoming_duties = [
        s for s in validator_duty_services if s.has_ongoing_duty or s.has_upcoming_duty
    ]
    while len(services_with_upcoming_duties) > 0:
        service_names = [s.__class__.__name__ for s in services_with_upcoming_duties]
        _logger.info(
            f"Waiting for validator duties to be completed for { ', '.join(service_names) }"
        )
        wait_tasks = [
            asyncio.create_task(s.wait_for_duty_completion())
            for s in services_with_upcoming_duties
        ]
        await asyncio.gather(*wait_tasks)
        services_with_upcoming_duties = [
            s
            for s in validator_duty_services
            if s.has_ongoing_duty or s.has_upcoming_duty
        ]

    _logger.info("Shutting down...")
    shutdown_event.set()


_shutdown_tasks = set()


def shutdown_handler(
    signo: int,
    validator_duty_services: list[ValidatorDutyService],
    shutdown_event: asyncio.Event,
) -> None:
    _logger.info(f"Received shutdown signal {signal.Signals(signo).name}")
    task = asyncio.create_task(
        shut_down(
            validator_duty_services=validator_duty_services,
            shutdown_event=shutdown_event,
        )
    )
    _shutdown_tasks.add(task)
    task.add_done_callback(_shutdown_tasks.discard)
