import asyncio
import logging
import math
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from prometheus_client import Counter, Histogram

from observability import ErrorType, get_shared_metrics
from providers import BeaconChain, BeaconNode
from schemas import SchemaBeaconAPI
from tasks import TaskManager

(_ERRORS_METRIC,) = get_shared_metrics()


def _setup_head_event_time_metric(
    seconds_per_slot: int,
    seconds_per_interval: float,
) -> Histogram:
    """
    We want to track at which point into the slot a head event was received
    from each connected beacon node.
    In the first 1/3rd of the slot it makes sense to track this in a finer
    way, e.g. in buckets of 250ms second.
    During the rest of the slot, a coarser approach is sufficient since
    head events received that late are not that valuable anyway.
    """
    step_fine = 0.25  # first part:  250 ms
    step_coarse = 1.0  # second part: 1,000 ms

    # Fine-grained head event timing buckets
    ticks_fine = int(seconds_per_interval / step_fine)
    fine_buckets = [step_fine * k for k in range(ticks_fine)]

    # Coarser tracking for the remainder of the slot
    first_coarse = math.ceil(seconds_per_interval / step_coarse) * step_coarse
    ticks_coarse = math.ceil((seconds_per_slot - first_coarse) / step_coarse) + 1
    coarse_buckets = [first_coarse + step_coarse * k for k in range(ticks_coarse)]

    return Histogram(
        "head_event_time",
        "Time into slot at which a head event for the slot was received",
        labelnames=["host"],
        buckets=fine_buckets + coarse_buckets,
    )


class EventConsumerService:
    _processed_events_metric = Counter(
        "vc_processed_beacon_node_events",
        "Successfully processed beacon node events",
        labelnames=["host", "event_type"],
    )

    def __init__(
        self,
        beacon_nodes: list[BeaconNode],
        beacon_chain: BeaconChain,
        scheduler: AsyncIOScheduler,
        task_manager: TaskManager,
    ):
        self.beacon_nodes = beacon_nodes
        self.beacon_chain: BeaconChain = beacon_chain
        self.scheduler = scheduler
        self.task_manager = task_manager

        self.logger = logging.getLogger(self.__class__.__name__)

        self.event_handlers: dict[
            type[SchemaBeaconAPI.BeaconNodeEvent],
            list[Callable[[Any], Coroutine[Any, Any, None]]],
        ] = defaultdict(list)

        self._head_event_time_metric = _setup_head_event_time_metric(
            seconds_per_slot=beacon_chain.SECONDS_PER_SLOT,
            seconds_per_interval=beacon_chain.SECONDS_PER_INTERVAL,
        )

    def start(self) -> None:
        for beacon_node in self.beacon_nodes:
            self.task_manager.submit_task(
                self.handle_events(beacon_node=beacon_node),
                name=f"handle_events_{beacon_node.base_url}",
            )

    def add_event_handler(
        self,
        event_handler: Callable[[Any], Coroutine[Any, Any, None]],
        event_type: type[SchemaBeaconAPI.BeaconNodeEvent],
    ) -> None:
        self.event_handlers[event_type].append(event_handler)

    async def handle_events(self, beacon_node: BeaconNode) -> None:
        self.logger.info(f"Subscribing to events from {beacon_node.host}")

        topics = ["head", "chain_reorg", "attester_slashing", "proposer_slashing"]

        try:
            async for event in beacon_node.subscribe_to_events(topics=topics):
                if (
                    hasattr(event, "slot")
                    and int(event.slot) < self.beacon_chain.current_slot
                ):
                    self.logger.warning(
                        f"Ignoring event for old slot {event.slot} from {beacon_node.host}. Current slot: {self.beacon_chain.current_slot}. Event: {event}"
                    )
                    continue

                if isinstance(event, SchemaBeaconAPI.HeadEvent):
                    self.logger.debug(f"New head @ {event.slot} : {event.block}")
                    self._head_event_time_metric.labels(host=beacon_node.host).observe(
                        self.beacon_chain.time_since_slot_start(slot=int(event.slot))
                    )
                elif isinstance(event, SchemaBeaconAPI.ChainReorgEvent):
                    self.logger.info(
                        f"Chain reorg of depth {event.depth} at slot {event.slot}, old head {event.old_head_block}, new head {event.new_head_block}",
                    )
                elif isinstance(event, SchemaBeaconAPI.AttesterSlashingEvent):
                    self.logger.debug(f"AttesterSlashingEvent: {event}")
                elif isinstance(event, SchemaBeaconAPI.ProposerSlashingEvent):
                    self.logger.debug(f"ProposerSlashingEvent: {event}")
                else:
                    raise NotImplementedError(f"Unsupported event type: {type(event)}")  # noqa: TRY301

                for event_type, handlers in self.event_handlers.items():
                    if isinstance(event, event_type):
                        for handler in handlers:
                            self.task_manager.submit_task(
                                handler(event),
                                name=f"{self.__class__.__name__}.handler-{event_type}-{handler.__name__}-{uuid4().hex}",
                            )

                self._processed_events_metric.labels(
                    host=beacon_node.host,
                    event_type=type(event).__name__,
                ).inc()

        except asyncio.CancelledError:
            raise
        except Exception as e:
            beacon_node.score -= BeaconNode.SCORE_DELTA_FAILURE
            _ERRORS_METRIC.labels(
                error_type=ErrorType.EVENT_CONSUMER.value,
            ).inc()
            self.logger.exception(
                f"Error occurred while processing beacon node events from {beacon_node.host} ({e!r}). Reconnecting in 1 second...",
            )
            self.task_manager.submit_task(
                self.handle_events(beacon_node=beacon_node),
                delay=1.0,
                name=f"handle_events_{beacon_node.base_url}",
            )
        else:
            # The SSE stream ended without any error.
            # This is not expected to happen normally.
            # We want to resubscribe to it right away.
            self.task_manager.submit_task(
                self.handle_events(beacon_node=beacon_node),
                name=f"handle_events_{beacon_node.base_url}",
            )
