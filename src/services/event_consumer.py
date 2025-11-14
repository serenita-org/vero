import asyncio
import logging
from collections import deque
from collections.abc import Callable, Coroutine, Hashable
from typing import Any
from uuid import uuid4

from observability import ErrorType
from providers import BeaconNode, Vero
from schemas import SchemaBeaconAPI


class EventConsumerService:
    def __init__(
        self,
        beacon_nodes: list[BeaconNode],
        vero: Vero,
    ):
        self.beacon_nodes = beacon_nodes
        self.beacon_chain = vero.beacon_chain
        self.scheduler = vero.scheduler
        self.task_manager = vero.task_manager

        self.logger = logging.getLogger(self.__class__.__name__)
        self.metrics = vero.metrics

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

    def start(self) -> None:
        for beacon_node in self.beacon_nodes:
            self.task_manager.create_task(
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

    def _handle_event(
        self, event: SchemaBeaconAPI.BeaconNodeEvent, beacon_node: BeaconNode
    ) -> None:
        if hasattr(event, "slot") and int(event.slot) < self.beacon_chain.current_slot:
            self.logger.warning(
                f"Ignoring event for old slot {event.slot} from {beacon_node.host}. Current slot: {self.beacon_chain.current_slot}. Event: {event}"
            )
            return

        event_type = type(event).__name__

        if isinstance(event, SchemaBeaconAPI.HeadEvent):
            self.metrics.head_event_time_h.labels(host=beacon_node.host).observe(
                self.beacon_chain.time_since_slot_start(slot=int(event.slot))
            )
            if not self._has_seen_event(event):
                self.logger.debug(
                    f"[{beacon_node.host}] New head @ {event.slot} : {event.block}"
                )
                for head_handler in self.head_event_handlers:
                    self.task_manager.create_task(
                        head_handler(event, beacon_node.host),
                        name=f"{self.__class__.__name__}.handler-{event_type}-{head_handler.__name__}-{uuid4().hex}",
                    )
        elif isinstance(event, SchemaBeaconAPI.ChainReorgEvent):
            if not self._has_seen_event(event):
                self.logger.info(
                    f"Chain reorg of depth {event.depth} at slot {event.slot}, old head {event.old_head_block}, new head {event.new_head_block}",
                )
                for reorg_handler in self.reorg_event_handlers:
                    self.task_manager.create_task(
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
            if not self._has_seen_event(event):
                self.logger.debug(f"{event_type}: {event.dedup_key}")
                for sl_handler in self.slashing_event_handlers:
                    self.task_manager.create_task(
                        sl_handler(event),
                        name=f"{self.__class__.__name__}.handler-{event_type}-{sl_handler.__name__}-{uuid4().hex}",
                    )
        else:
            raise NotImplementedError(f"Unsupported event type: {event_type}")

        self.metrics.vc_processed_beacon_node_events_c.labels(
            host=beacon_node.host,
            event_type=event_type,
        ).inc()

    async def handle_events(self, beacon_node: BeaconNode) -> None:
        self.logger.debug(f"Subscribing to events from {beacon_node.host}")

        topics = ["head", "chain_reorg", "attester_slashing", "proposer_slashing"]

        try:
            async for event in beacon_node.subscribe_to_events(topics=topics):
                self._handle_event(event=event, beacon_node=beacon_node)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            beacon_node.score -= BeaconNode.SCORE_DELTA_FAILURE
            self.metrics.errors_c.labels(
                error_type=ErrorType.EVENT_CONSUMER.value,
            ).inc()
            self.logger.exception(
                f"Error occurred while processing beacon node events from {beacon_node.host} ({e!r}). Reconnecting in 10 seconds...",
            )
            self.task_manager.create_task(
                self.handle_events(beacon_node=beacon_node),
                delay=10.0,
                name=f"handle_events_{beacon_node.base_url}",
            )
        else:
            # The SSE stream ended without any error.
            # This is not expected to happen normally.
            # We want to resubscribe to it right away.
            self.task_manager.create_task(
                self.handle_events(beacon_node=beacon_node),
                name=f"handle_events_{beacon_node.base_url}",
            )
