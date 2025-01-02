import asyncio
import datetime
import logging
from enum import Enum
from typing import TYPE_CHECKING, TypedDict, Unpack

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from opentelemetry import trace
from prometheus_client import Histogram

from args import CLIArgs
from observability import ErrorType, get_shared_metrics
from providers import BeaconChain, MultiBeaconNode, RemoteSigner
from schemas import SchemaBeaconAPI

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
    remote_signer: RemoteSigner
    validator_status_tracker_service: "ValidatorStatusTrackerService"
    scheduler: AsyncIOScheduler
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
        self.remote_signer = kwargs["remote_signer"]
        self.validator_status_tracker_service = kwargs[
            "validator_status_tracker_service"
        ]
        self.scheduler = kwargs["scheduler"]
        self.cli_args = kwargs["cli_args"]

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.getLogger().level)
        self.tracer = trace.get_tracer(self.__class__.__name__)

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

        # This variable defines the interval (in seconds) before a validator duty is
        # scheduled (/or ongoing) during which an immediate shutdown is deferred.
        # Instead of shutting down immediately, Vero will wait for the
        # duty to complete, minimizing the risk of missing a scheduled duty.
        self._shutdown_defer_interval = 3

    def start(self) -> None:
        # Every service should start its
        # reocurring scheduled jobs here.
        raise NotImplementedError

    async def handle_head_event(self, event: SchemaBeaconAPI.HeadEvent) -> None:
        raise NotImplementedError

    async def handle_reorg_event(self, event: SchemaBeaconAPI.ChainReorgEvent) -> None:
        self.logger.debug(
            f"Handling reorg event at slot {event.slot}, new head block {event.new_head_block}"
        )
        self.scheduler.add_job(
            self.update_duties,
            id=f"{self.__class__.__name__}.update_duties",
            replace_existing=True,
        )

    @property
    def has_ongoing_duty(self) -> bool:
        return (
            self._last_slot_duty_completed_for < self._last_slot_duty_started_for
            and self._last_slot_duty_started_for == self.beacon_chain.current_slot
        )

    @property
    def next_duty_slot(self) -> int | None:
        raise NotImplementedError

    @property
    def next_duty_run_time(self) -> datetime.datetime | None:
        raise NotImplementedError

    @property
    def has_upcoming_duty(self) -> bool:
        next_duty_run_time = self.next_duty_run_time  # Cache the property value
        if next_duty_run_time is None:
            return False

        time_to_next_duty_run_time = (
            next_duty_run_time - datetime.datetime.now(pytz.utc)
        ).total_seconds()
        return time_to_next_duty_run_time < self._shutdown_defer_interval

    async def wait_for_duty_completion(self) -> None:
        """
        This functions waits until any upcoming validator duty
        is performed.
        """
        if not (self.has_ongoing_duty or self.has_upcoming_duty):
            return

        slot_to_complete_duty_for = self.next_duty_slot
        if slot_to_complete_duty_for is None:
            return
        self.logger.info(
            f"Waiting for validator duty to be completed (slot {slot_to_complete_duty_for})"
        )
        while self._last_slot_duty_completed_for < slot_to_complete_duty_for:  # noqa: ASYNC110
            await asyncio.sleep(0.01)
        self.logger.info("Validator duty completed")

    async def _update_duties(self) -> None:
        raise NotImplementedError

    async def update_duties(self) -> None:
        # Calls self._update_duties once per epoch
        next_run_time = None
        try:
            await self._update_duties()
        except Exception as e:
            _ERRORS_METRIC.labels(error_type=ErrorType.DUTIES_UPDATE.value).inc()
            self.logger.error(
                f"Failed to update duties: {e!r}",
                exc_info=self.logger.isEnabledFor(logging.DEBUG),
            )
            next_run_time = datetime.datetime.now(tz=pytz.UTC) + datetime.timedelta(
                seconds=1,
            )
        finally:
            # Schedule the next update of duties
            if next_run_time is None:
                next_run_time = self.beacon_chain.get_datetime_for_slot(
                    slot=(self.beacon_chain.current_epoch + 1)
                    * self.beacon_chain.spec.SLOTS_PER_EPOCH,
                )
            self.logger.debug(f"Next update_duties job run time: {next_run_time}")
            self.scheduler.add_job(
                self.update_duties,
                "date",
                next_run_time=next_run_time,
                id=f"{self.__class__.__name__}.update_duties",
                replace_existing=True,
            )
