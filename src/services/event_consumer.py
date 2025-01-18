import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from prometheus_client import Counter

from providers import BeaconChain, BeaconNode, MultiBeaconNode
from schemas import SchemaBeaconAPI
from tasks import TaskManager

_VC_PROCESSED_BEACON_NODE_EVENTS = Counter(
    "vc_processed_beacon_node_events",
    "Successfully processed beacon node events",
    labelnames=["host", "event_type"],
)


class EventConsumerService:
    def __init__(
        self,
        multi_beacon_node: MultiBeaconNode,
        beacon_chain: BeaconChain,
        scheduler: AsyncIOScheduler,
        task_manager: TaskManager,
    ):
        self.multi_beacon_node = multi_beacon_node
        self.beacon_chain: BeaconChain = beacon_chain
        self.scheduler = scheduler
        self.task_manager = task_manager

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.getLogger().level)

        self.event_handlers: dict[
            type[SchemaBeaconAPI.BeaconNodeEvent],
            list[Callable[[Any], Coroutine[Any, Any, None]]],
        ] = defaultdict(list)

    def start(self) -> None:
        self.task_manager.submit_task(self.handle_events())

    def add_event_handler(
        self,
        event_handler: Callable[[Any], Coroutine[Any, Any, None]],
        event_type: type[SchemaBeaconAPI.BeaconNodeEvent],
    ) -> None:
        self.event_handlers[event_type].append(event_handler)

    async def handle_events(self) -> None:
        beacon_node = self.multi_beacon_node.best_beacon_node
        self.logger.info(f"Subscribing to events from {beacon_node.host}")
        primary_bn = self.multi_beacon_node.primary_beacon_node

        topics = ["head", "chain_reorg", "attester_slashing", "proposer_slashing"]
        if "grandine" in beacon_node.node_version.lower():
            # Grandine doesn't support the slashing SSE events
            for t in ("attester_slashing", "proposer_slashing"):
                topics.remove(t)

        try:
            async for event in beacon_node.subscribe_to_events(topics=topics):
                if (
                    hasattr(event, "slot")
                    and int(event.slot) < self.beacon_chain.current_slot
                ):
                    self.logger.warning(
                        f"Ignoring event for old slot {event.slot} from {beacon_node}. Current slot: {self.beacon_chain.current_slot}. Event: {event}"
                    )
                    continue

                if isinstance(event, SchemaBeaconAPI.HeadEvent):
                    self.logger.debug(f"New head @ {event.slot} : {event.block}")
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

                _VC_PROCESSED_BEACON_NODE_EVENTS.labels(
                    host=beacon_node.host,
                    event_type=type(event).__name__,
                ).inc()

                # Switch back to primary beacon node SSE stream whenever possible
                if (
                    beacon_node != primary_bn
                    and primary_bn.score == BeaconNode.MAX_SCORE
                ):
                    self.logger.info(
                        f"Switching SSE subscription from {beacon_node.host} back to primary beacon node {primary_bn.host}"
                    )
                    break

            # We may break out of the for loop to switch nodes, or if the SSE ends
            # naturally. -> In both cases we want to reconnect/resubscribe.
            self.task_manager.submit_task(
                self.handle_events(), name=f"{self.__class__.__name__}.handle_events"
            )

        except Exception as e:
            beacon_node.score -= BeaconNode.SCORE_DELTA_FAILURE
            self.logger.error(
                f"Error occurred while processing beacon node events from {beacon_node.host} ({e!r}). Reconnecting in 1 second...",
                exc_info=self.logger.isEnabledFor(logging.DEBUG),
            )
            self.task_manager.submit_task(self.handle_events(), delay=1.0)
