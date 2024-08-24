import asyncio
import logging
from typing import Callable, Type

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from prometheus_client import Counter

from providers import MultiBeaconNode
from providers.beacon_node import _SCORE_DELTA_FAILURE
from schemas import SchemaBeaconAPI


_VC_PROCESSED_BEACON_NODE_EVENTS = Counter(
    "vc_processed_beacon_node_events",
    "Successfully processed beacon node events",
    labelnames=["host", "event_type"],
)


class EventConsumerService:
    def __init__(
        self,
        multi_beacon_node: MultiBeaconNode,
        scheduler: AsyncIOScheduler,
    ):
        self.multi_beacon_node = multi_beacon_node
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.getLogger().level)

        self.event_handlers: list[
            tuple[Callable, list[Type[SchemaBeaconAPI.BeaconNodeEvent]]]
        ] = []

        self.scheduler = scheduler

    def add_event_handler(
        self,
        event_handler: Callable,
        event_types: list[Type[SchemaBeaconAPI.BeaconNodeEvent]],
    ):
        self.event_handlers.append((event_handler, event_types))

    async def handle_events(self):
        try:
            beacon_node = self.multi_beacon_node.best_beacon_node
            self.logger.info(f"Subscribing to events from {beacon_node.host}")

            topics = ["head", "chain_reorg", "attester_slashing", "proposer_slashing"]
            if "grandine" in beacon_node.node_version.lower():
                # Grandine doesn't support the slashing SSE events
                for t in ("attester_slashing", "proposer_slashing"):
                    topics.remove(t)

            async for event in beacon_node.subscribe_to_events(topics=topics):
                if (
                    hasattr(event, "execution_optimistic")
                    and event.execution_optimistic
                ):
                    self.logger.error(
                        f"Execution optimistic for event {event}, ignoring..."
                    )
                    beacon_node.score -= _SCORE_DELTA_FAILURE
                    continue

                if isinstance(event, SchemaBeaconAPI.HeadEvent):
                    self.logger.debug(f"New head @ {event.slot} : {event.block}")
                    for handler, event_types in self.event_handlers:
                        if SchemaBeaconAPI.HeadEvent in event_types:
                            self.scheduler.add_job(handler, kwargs=dict(event=event))
                elif isinstance(event, SchemaBeaconAPI.ChainReorgEvent):
                    self.logger.info(
                        f"Chain reorg of depth {event.depth} at slot {event.slot}, old head {event.old_head_block}, new head {event.new_head_block}"
                    )
                    for handler, event_types in self.event_handlers:
                        if SchemaBeaconAPI.ChainReorgEvent in event_types:
                            self.scheduler.add_job(handler)
                elif isinstance(event, SchemaBeaconAPI.AttesterSlashingEvent):
                    self.logger.debug(f"AttesterSlashingEvent: {event}")
                    for handler, event_types in self.event_handlers:
                        if SchemaBeaconAPI.AttesterSlashingEvent in event_types:
                            self.scheduler.add_job(handler, kwargs=dict(event=event))
                elif isinstance(event, SchemaBeaconAPI.ProposerSlashingEvent):
                    self.logger.debug(f"ProposerSlashingEvent: {event}")
                    for handler, event_types in self.event_handlers:
                        if SchemaBeaconAPI.ProposerSlashingEvent in event_types:
                            self.scheduler.add_job(handler, kwargs=dict(event=event))
                else:
                    raise NotImplementedError(f"Unsupported event type: {type(event)}")

                _VC_PROCESSED_BEACON_NODE_EVENTS.labels(
                    host=beacon_node.host,
                    event_type=type(event).__name__,
                ).inc()

        except Exception as e:
            self.logger.error(
                "Error occurred while processing beacon node events, reconnecting in 1 second..."
            )
            self.logger.exception(e)
            await asyncio.sleep(1)
            self.scheduler.add_job(self.handle_events)
