import asyncio
import logging
from math import floor
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from observability import Metrics
    from providers import BeaconChain


async def monitor_event_loop(
    beacon_chain: BeaconChain, metrics: Metrics, shutdown_event: asyncio.Event
) -> None:
    _logger = logging.getLogger("event-loop")
    event_loop = asyncio.get_running_loop()
    _start = event_loop.time()
    _interval = 0.1  # Check every 100 milliseconds
    _loop_lag_high_threshold = 0.5  # 500 milliseconds

    while not shutdown_event.is_set():
        await asyncio.sleep(_interval)
        lag = event_loop.time() - _start - _interval
        if lag > _loop_lag_high_threshold:
            _logger.warning(f"Event loop lag high: {lag}")
        time_since_slot_start = floor(
            beacon_chain.time_since_slot_start(slot=beacon_chain.current_slot)
        )
        metrics.event_loop_lag_h.labels(
            time_since_slot_start=time_since_slot_start
        ).observe(lag)
        metrics.event_loop_tasks_g.set(len(asyncio.all_tasks(event_loop)))
        _start = event_loop.time()
