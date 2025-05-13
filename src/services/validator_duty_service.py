import asyncio
import logging
from enum import Enum
from types import TracebackType
from typing import TYPE_CHECKING, Self, TypedDict, Unpack

import msgspec
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from opentelemetry import trace
from prometheus_client import Histogram

from args import CLIArgs
from observability import ErrorType, get_shared_metrics
from providers import BeaconChain, Keymanager, MultiBeaconNode, SignatureProvider
from providers.duty_cache import DutyCacheProvider
from schemas import SchemaBeaconAPI
from tasks import TaskManager

if TYPE_CHECKING:
    from services import ValidatorStatusTrackerService

(_ERRORS_METRIC,) = get_shared_metrics()


class ValidatorDuty(Enum):
    ATTESTATION = "attestation"
    ATTESTATION_AGGREGATION = "attestation-aggregation"
    BLOCK_PROPOSAL = "block-proposal"
    SYNC_COMMITTEE_MESSAGE = "sync-committee-message"
    SYNC_COMMITTEE_CONTRIBUTION = "sync-committee-contribution"


class ValidatorDutyServiceOptions(TypedDict):
    multi_beacon_node: MultiBeaconNode
    beacon_chain: BeaconChain
    signature_provider: SignatureProvider
    keymanager: Keymanager
    duty_cache_provider: DutyCacheProvider
    validator_status_tracker_service: "ValidatorStatusTrackerService"
    scheduler: AsyncIOScheduler
    task_manager: TaskManager
    cli_args: CLIArgs


class ValidatorDutyService:
    _duty_start_time_metric = Histogram(
        "duty_start_time",
        "Time into slot at which a duty starts",
        labelnames=["duty"],
        buckets=[
            item
            for sublist in [[i, i + 0.25, i + 0.5, i + 0.75] for i in range(12)]
            for item in sublist
        ],
    )
    _duty_submission_time_metric = Histogram(
        "duty_submission_time",
        "Time into slot at which data for a duty is about to be submitted",
        labelnames=["duty"],
        buckets=[
            item
            for sublist in [[i, i + 0.25, i + 0.5, i + 0.75] for i in range(12)]
            for item in sublist
        ],
    )

    def __init__(
        self,
        **kwargs: Unpack[ValidatorDutyServiceOptions],
    ):
        self.multi_beacon_node = kwargs["multi_beacon_node"]
        self.beacon_chain = kwargs["beacon_chain"]
        self.signature_provider = kwargs["signature_provider"]
        self.keymanager = kwargs["keymanager"]
        self.duty_cache_provider = kwargs["duty_cache_provider"]
        self.validator_status_tracker_service = kwargs[
            "validator_status_tracker_service"
        ]
        self.scheduler = kwargs["scheduler"]
        self.task_manager = kwargs["task_manager"]
        self.cli_args = kwargs["cli_args"]

        self.logger = logging.getLogger(self.__class__.__name__)
        self.tracer = trace.get_tracer(self.__class__.__name__)
        self.json_encoder = msgspec.json.Encoder()

        # Keeps track of the last slot for which this service started performing its
        # duty.
        # Prevents us from trying to perform the duty for the same slot twice.
        # Performing a slashable duty twice would fail because of the remote
        # signer's slashing protection but we can try to prevent the attempt
        # at signing too.
        self._last_slot_duty_started_for = -1

        # Keeps track of the last slot for which this
        # service completed performing its duty.
        # Allows us to wait for a duty to be completed
        # before taking further actions (e.g. shutting down).
        self._last_slot_duty_completed_for = -1

        # Avoids us updating validator duties multiple times
        # at the same time
        self._update_duties_lock = asyncio.Lock()

    async def __aenter__(self) -> Self:
        raise NotImplementedError

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        raise NotImplementedError

    async def handle_head_event(self, event: SchemaBeaconAPI.HeadEvent) -> None:
        raise NotImplementedError

    async def handle_reorg_event(self, event: SchemaBeaconAPI.ChainReorgEvent) -> None:
        self.logger.debug(
            f"Handling reorg event at slot {event.slot}, new head block {event.new_head_block}"
        )
        self.task_manager.submit_task(self.update_duties())

    @property
    def has_ongoing_duty(self) -> bool:
        return (
            self._last_slot_duty_completed_for < self._last_slot_duty_started_for
            and self._last_slot_duty_started_for == self.beacon_chain.current_slot
        )

    def has_duty_for_slot(self, slot: int) -> bool:
        raise NotImplementedError

    async def wait_for_duty_completion(self) -> None:
        current_slot = self.beacon_chain.current_slot  # Cache property value

        # Return immediately if we already completed the duty
        if self._last_slot_duty_completed_for == current_slot:
            self.logger.debug(f"Duty for slot {current_slot} already completed")
            return

        # Return immediately if there is no duty for this slot
        if (
            not self.has_duty_for_slot(current_slot)
            and self._last_slot_duty_started_for != current_slot
        ):
            self.logger.debug(f"No duty for slot {current_slot}")
            return

        self.logger.info(
            f"Waiting for validator duty to be completed (slot {current_slot})"
        )
        while self._last_slot_duty_completed_for < current_slot:  # noqa: ASYNC110
            await asyncio.sleep(0.01)
        self.logger.info("Validator duty completed")

    async def on_new_slot(self, slot: int, is_new_epoch: bool) -> None:
        raise NotImplementedError

    async def _update_duties(self) -> None:
        raise NotImplementedError

    async def update_duties(self) -> None:
        # Calls self._update_duties, retrying until it succeeds, with backoff

        if self._update_duties_lock.locked():
            # Duties already being updated
            self.logger.debug("Duties already being updated, returning...")
            return

        await self._update_duties_lock.acquire()
        self.logger.info("Updating duties")
        epoch_at_start = self.beacon_chain.current_epoch

        # Backoff parameters
        initial_delay = 1.0  # Starting delay between API calls
        max_delay = 10.0  # Maximum delay between API calls
        current_delay = initial_delay

        while self.beacon_chain.current_epoch == epoch_at_start:
            try:
                await self._update_duties()
                break
            except Exception as e:
                _ERRORS_METRIC.labels(error_type=ErrorType.DUTIES_UPDATE.value).inc()
                self.logger.error(
                    f"Failed to update duties: {e!r}",
                    exc_info=self.logger.isEnabledFor(logging.DEBUG),
                )

                # Wait for the current delay before retrying again
                await asyncio.sleep(current_delay)

                # Increase the delay for the next iteration, up to the max
                current_delay = min(current_delay * 2, max_delay)

        self._update_duties_lock.release()
