import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import uuid4

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
        self.scheduler = scheduler

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.getLogger().level)

        self.event_handlers: dict[
            type[SchemaBeaconAPI.BeaconNodeEvent],
            list[Callable[[Any], Coroutine[Any, Any, None]]],
        ] = defaultdict(list)

    def start(self) -> None:
        self.scheduler.add_job(
            self.handle_events,
            id=f"{self.__class__.__name__}.handle_events",
        )

    def add_event_handler(
        self,
        event_handler: Callable[[Any], Coroutine[Any, Any, None]],
        event_type: type[SchemaBeaconAPI.BeaconNodeEvent],
    ) -> None:
        self.event_handlers[event_type].append(event_handler)

    async def handle_events(self) -> None:
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
                        f"Execution optimistic for event {event}, ignoring...",
                    )
                    beacon_node.score -= _SCORE_DELTA_FAILURE
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
                            self.scheduler.add_job(
                                handler,
                                kwargs=dict(event=event),
                                id=f"{self.__class__.__name__}.handler-{event_type}-{handler.__name__}-{uuid4().hex}",
                            )

                _VC_PROCESSED_BEACON_NODE_EVENTS.labels(
                    host=beacon_node.host,
                    event_type=type(event).__name__,
                ).inc()

        except Exception as e:
            self.logger.error(
                f"Error occurred while processing beacon node events ({e!r}). Reconnecting in 1 second...",
                exc_info=self.logger.isEnabledFor(logging.DEBUG),
            )
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            # Expected to happen when Vero shuts down
            self.logger.info("Stopped event consumer")
            return

        self.scheduler.add_job(
            self.handle_events,
            id=f"{self.__class__.__name__}.handle_events",
            replace_existing=True,
        )
