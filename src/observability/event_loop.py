import asyncio
import logging

from prometheus_client import Gauge, Histogram

EVENT_LOOP_LAG = Histogram(
    "event_loop_lag_seconds",
    "Estimate of event loop lag",
)
EVENT_LOOP_TASKS = Gauge(
    "event_loop_tasks",
    "Number of tasks in event loop",
)


async def monitor_event_loop() -> None:
    _logger = logging.getLogger("event-loop")
    event_loop = asyncio.get_event_loop()
    _start = event_loop.time()
    _interval = 0.1  # Check every 100 milliseconds
    _loop_lag_high_threshold = 0.5  # 500 milliseconds

    while True:
        await asyncio.sleep(_interval)
        lag = event_loop.time() - _start - _interval
        if lag > _loop_lag_high_threshold:
            _logger.warning(f"Event loop lag high: {lag}")
        EVENT_LOOP_LAG.observe(lag)
        EVENT_LOOP_TASKS.set(len(asyncio.all_tasks(event_loop)))
        _start = event_loop.time()
