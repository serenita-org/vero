from prometheus_client import Histogram, Gauge

EVENT_LOOP_LAG = Histogram(
    "event_loop_lag_seconds",
    "Estimate of event loop lag",
)
EVENT_LOOP_TASKS = Gauge(
    "event_loop_tasks",
    "Number of tasks in event loop",
)
