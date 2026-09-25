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
        self.cli_args = vero.cli_args

        self.head_event_handlers: list[
            Callable[[SchemaBeaconAPI.HeadV2Event, str], Coroutine[Any, Any, None]]
        ] = []
        self.execution_payload_available_event_handlers: list[
            Callable[
                [SchemaBeaconAPI.ExecutionPayloadAvailableEvent],
                Coroutine[Any, Any, None],
            ]
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
        self.payload_attributes_event_handlers: list[
            Callable[
                [SchemaBeaconAPI.PayloadAttributesEvent], Coroutine[Any, Any, None]
            ]
        ] = []
        self.bid_event_handlers: list[
            Callable[
                [SchemaBeaconAPI.ExecutionPayloadBidEvent], Coroutine[Any, Any, None]
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
            [SchemaBeaconAPI.HeadV2Event, str], Coroutine[Any, Any, None]
        ],
    ) -> None:
        self.head_event_handlers.append(event_handler)

    def add_execution_payload_available_event_handler(
        self,
        event_handler: Callable[
            [SchemaBeaconAPI.ExecutionPayloadAvailableEvent], Coroutine[Any, Any, None]
        ],
    ) -> None:
        self.execution_payload_available_event_handlers.append(event_handler)

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

    def add_payload_attributes_event_handler(
        self,
        event_handler: Callable[
            [SchemaBeaconAPI.PayloadAttributesEvent],
            Coroutine[Any, Any, None],
        ],
    ) -> None:
        self.payload_attributes_event_handlers.append(event_handler)

    def add_bid_event_handler(
        self,
        event_handler: Callable[
            [SchemaBeaconAPI.ExecutionPayloadBidEvent],
            Coroutine[Any, Any, None],
        ],
    ) -> None:
        self.bid_event_handlers.append(event_handler)

    def _has_seen_event(self, event: SchemaBeaconAPI.BeaconNodeEvent) -> bool:
        key = event.dedup_key

        if key in self._recent_event_keys:
            return True

        self._recent_event_keys.append(key)
        return False

    def _handle_event(
        self, event: SchemaBeaconAPI.BeaconNodeEvent, beacon_node: BeaconNode
    ) -> None:
        event_slot = None
        if isinstance(
            event,
            SchemaBeaconAPI.ExecutionPayloadAvailableEvent
            | SchemaBeaconAPI.ChainReorgEvent,
        ):
            event_slot = int(event.slot)
        elif isinstance(event, SchemaBeaconAPI.HeadV2Event):
            event_slot = int(event.data.slot)

        if event_slot and event_slot < self.beacon_chain.current_slot:
            self.logger.warning(
                f"Ignoring event for old slot {event_slot} from {beacon_node.netloc}. Current slot: {self.beacon_chain.current_slot}. Event: {event}"
            )
            return

        event_type = type(event).__name__

        if isinstance(event, SchemaBeaconAPI.HeadV2Event):
            self.metrics.head_event_time_h.labels(netloc=beacon_node.netloc).observe(
                self.beacon_chain.time_since_slot_start(slot=int(event.data.slot))
            )
            if not self._has_seen_event(event):
                self.logger.debug(
                    f"[{beacon_node.netloc}] New head @ {event.data.slot} : {event.data.block}"
                )
                for head_handler in self.head_event_handlers:
                    self.task_manager.create_task(
                        head_handler(event, beacon_node.netloc),
                        name=f"{self.__class__.__name__}.handler-{event_type}-{head_handler.__name__}-{uuid4().hex}",
                    )
        elif isinstance(event, SchemaBeaconAPI.ExecutionPayloadAvailableEvent):
            # TODO metric - track how far into the slot this happens on each connected node?
            if not self._has_seen_event(event):
                self.logger.debug(
                    f"Execution payload available @ {event.slot} : {event.block_root}"
                )
                for epa_handler in self.execution_payload_available_event_handlers:
                    self.task_manager.create_task(
                        epa_handler(event),
                        name=f"{self.__class__.__name__}.handler-{event_type}-{epa_handler.__name__}-{uuid4().hex}",
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
        elif isinstance(
            event,
            SchemaBeaconAPI.PayloadAttributesEvent,
        ):
            # TODO we may want to keep track of how many times we saw a specific
            #  payload attributes event inside BidSelector, in which case we should
            #  remote the _has_seen_event filter here.
            if not self._has_seen_event(event):
                self.logger.debug(f"{event_type}: {event.dedup_key}")
                for pa_handler in self.payload_attributes_event_handlers:
                    self.task_manager.create_task(
                        pa_handler(event),
                        name=f"{self.__class__.__name__}.handler-{event_type}-{pa_handler.__name__}-{uuid4().hex}",
                    )
        elif isinstance(event, SchemaBeaconAPI.ExecutionPayloadBidEvent):
            if not self._has_seen_event(event):
                self.logger.debug(f"Execution payload bid event: {event}")
                for bid_handler in self.bid_event_handlers:
                    self.task_manager.create_task(
                        bid_handler(event),
                        name=f"{self.__class__.__name__}.handler-{event_type}-{bid_handler.__name__}-{uuid4().hex}",
                    )
        else:
            raise NotImplementedError(f"Unsupported event type: {event_type}")

        self.metrics.vc_processed_beacon_node_events_c.labels(
            netloc=beacon_node.netloc,
            event_type=event_type,
        ).inc()

    async def handle_events(self, beacon_node: BeaconNode) -> None:
        self.logger.debug(f"Subscribing to events from {beacon_node.netloc}")

        topics = [
            # TODO use head_v2? !!!
            "head_v2",
            "execution_payload_available",
            "chain_reorg",
            "attester_slashing",
            "proposer_slashing",
        ]

        if not self.cli_args.disable_bid_selection:
            topics.append("payload_attributes")
            topics.append("execution_payload_bid")

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
                f"Error occurred while processing beacon node events from {beacon_node.netloc} ({e!r}). Reconnecting in 10 seconds...",
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
