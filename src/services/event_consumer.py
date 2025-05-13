import asyncio
import logging
import math
from collections import deque
from collections.abc import Callable, Coroutine, Hashable
from typing import Any
from uuid import uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from prometheus_client import Counter, Histogram

from observability import ErrorType, get_shared_metrics
from providers import BeaconChain, BeaconNode
from schemas import SchemaBeaconAPI
from tasks import TaskManager

(_ERRORS_METRIC,) = get_shared_metrics()
_HEAD_EVENT_TIME_METRIC = None


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
    global _HEAD_EVENT_TIME_METRIC

    if _HEAD_EVENT_TIME_METRIC is None:
        step_fine = 0.25  # first part:  250 ms
        step_coarse = 1.0  # second part: 1,000 ms

        # Fine-grained head event timing buckets
        ticks_fine = int(seconds_per_interval / step_fine)
        fine_buckets = [step_fine * k for k in range(ticks_fine)]

        # Coarser tracking for the remainder of the slot
        first_coarse = math.ceil(seconds_per_interval / step_coarse) * step_coarse
        ticks_coarse = math.ceil((seconds_per_slot - first_coarse) / step_coarse) + 1
        coarse_buckets = [first_coarse + step_coarse * k for k in range(ticks_coarse)]

        _HEAD_EVENT_TIME_METRIC = Histogram(
            "head_event_time",
            "Time into slot at which a head event for the slot was received",
            labelnames=["host"],
            buckets=fine_buckets + coarse_buckets,
        )
    return _HEAD_EVENT_TIME_METRIC


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

        self.head_event_handlers: list[
            Callable[[SchemaBeaconAPI.HeadEvent, str], Coroutine[Any, Any, None]]
        ] = []
        self.reorg_event_handlers: list[
            Callable[[SchemaBeaconAPI.ChainReorgEvent], Coroutine[Any, Any, None]]
        ] = []
        self.slashing_event_handlers: list[
            Callable[
                [
                    SchemaBeaconAPI.AttesterSlashingEvent
                    | SchemaBeaconAPI.ProposerSlashingEvent
                ],
                Coroutine[Any, Any, None],
            ]
        ] = []

        self._recent_event_keys: deque[Hashable] = deque(maxlen=10 * len(beacon_nodes))

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

    def add_head_event_handler(
        self,
        event_handler: Callable[
            [SchemaBeaconAPI.HeadEvent, str], Coroutine[Any, Any, None]
        ],
    ) -> None:
        self.head_event_handlers.append(event_handler)

    def add_reorg_event_handler(
        self,
        event_handler: Callable[
            [SchemaBeaconAPI.ChainReorgEvent], Coroutine[Any, Any, None]
        ],
    ) -> None:
        self.reorg_event_handlers.append(event_handler)

    def add_slashing_event_handler(
        self,
        event_handler: Callable[
            [
                SchemaBeaconAPI.AttesterSlashingEvent
                | SchemaBeaconAPI.ProposerSlashingEvent
            ],
            Coroutine[Any, Any, None],
        ],
    ) -> None:
        self.slashing_event_handlers.append(event_handler)

    def _has_seen_event(self, event: SchemaBeaconAPI.DeduplicableEvent) -> bool:
        key = event.dedup_key

        if key in self._recent_event_keys:
            return True

        self._recent_event_keys.append(key)
        return False

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

                event_type = type(event).__name__

                if isinstance(event, SchemaBeaconAPI.HeadEvent):
                    self.logger.debug(f"New head @ {event.slot} : {event.block}")
                    self._head_event_time_metric.labels(host=beacon_node.host).observe(
                        self.beacon_chain.time_since_slot_start(slot=int(event.slot))
                    )
                    for head_handler in self.head_event_handlers:
                        self.task_manager.submit_task(
                            head_handler(event, beacon_node.host),
                            name=f"{self.__class__.__name__}.handler-{event_type}-{head_handler.__name__}-{uuid4().hex}",
                        )
                elif isinstance(event, SchemaBeaconAPI.ChainReorgEvent):
                    self.logger.info(
                        f"Chain reorg of depth {event.depth} at slot {event.slot}, old head {event.old_head_block}, new head {event.new_head_block}",
                    )
                    for reorg_handler in self.reorg_event_handlers:
                        if not self._has_seen_event(event):
                            self.task_manager.submit_task(
                                reorg_handler(event),
                                name=f"{self.__class__.__name__}.handler-{event_type}-{reorg_handler.__name__}-{uuid4().hex}",
                            )
                elif isinstance(
                    event,
                    (
                        SchemaBeaconAPI.AttesterSlashingEvent,
                        SchemaBeaconAPI.ProposerSlashingEvent,
                    ),
                ):
                    self.logger.debug(f"{type(event)}: {event}")
                    for sl_handler in self.slashing_event_handlers:
                        if not self._has_seen_event(event):
                            self.task_manager.submit_task(
                                sl_handler(event),
                                name=f"{self.__class__.__name__}.handler-{event_type}-{sl_handler.__name__}-{uuid4().hex}",
                            )
                else:
                    raise NotImplementedError(f"Unsupported event type: {event_type}")  # noqa: TRY301

                self._processed_events_metric.labels(
                    host=beacon_node.host,
                    event_type=event_type,
                ).inc()

                # TODO
                #  ... think about this case
                #      3 beacon nodes
                #      1 of them has a bug, forks off and emits head events
                #      ... we may fail to attest here since _last_slot_duty_started_for
                #          has already been set by the faulty node and consensus will never
                #          be reached on its head block root!
                #      this can be avoided by setting _last_slot_duty_started_for later on,
                #      once consensus has been reached (or introducing some new logic that accounts for this case)
                #      ... BUT we would not want to attest early to an old head if we have
                #      already seen a head event for the current slot
                #      ... feels like there's a tradeoff here and we can't get best of both?
                #      HMMM perhaps an entire logic change makes sense here - emit the head event
                #      only once it's been seen by multiple BNs? It would avoid the polling we do
                #      ...

        except asyncio.CancelledError:
            raise
        except Exception:
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
