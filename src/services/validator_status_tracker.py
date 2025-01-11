import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from prometheus_client import Gauge

from observability import ErrorType, get_shared_metrics
from providers import BeaconChain, MultiBeaconNode, RemoteSigner
from schemas import SchemaBeaconAPI, SchemaValidator
from schemas.validator import (
    ACTIVE_STATUSES,
    EXITED_STATUSES,
    PENDING_STATUSES,
    SLASHED_STATUSES,
    WITHDRAWAL_STATUSES,
)
from tasks import TaskManager

_VALIDATORS_COUNT = Gauge(
    "validator_status",
    "Amount of validators per status",
    labelnames=["status"],
    multiprocess_mode="max",
)
_SLASHING_DETECTED = Gauge(
    "slashing_detected",
    "1 if any of the connected validators have been slashed, 0 otherwise",
    multiprocess_mode="max",
)
_SLASHING_DETECTED.set(0)
(_ERRORS_METRIC,) = get_shared_metrics()


class ValidatorStatusTrackerService:
    def __init__(
        self,
        multi_beacon_node: MultiBeaconNode,
        beacon_chain: BeaconChain,
        remote_signer: RemoteSigner,
        scheduler: AsyncIOScheduler,
        task_manager: TaskManager,
    ):
        self.multi_beacon_node = multi_beacon_node
        self.beacon_chain = beacon_chain
        self.remote_signer = remote_signer
        self.scheduler = scheduler
        self.task_manager = task_manager

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.getLogger().level)

        self._slashing_detected = False

        self.active_validators: list[SchemaValidator.ValidatorIndexPubkey] = []
        self.pending_validators: list[SchemaValidator.ValidatorIndexPubkey] = []

    async def initialize(self) -> None:
        # Call the internal _update function explicitly at initialization time.
        # If we fail to retrieve our validator statuses, it doesn't make sense
        # to continue initializing the validator client since we don't know
        # which validators to retrieve duties for.
        await self._update_validator_statuses(minimal_update=True)
        self.task_manager.submit_task(self.update_validator_statuses())

    @property
    def any_active_or_pending_validators(self) -> bool:
        return any(self.active_validators) or any(self.pending_validators)

    @property
    def slashing_detected(self) -> bool:
        return self._slashing_detected

    @slashing_detected.setter
    def slashing_detected(self, value: bool) -> None:
        self._slashing_detected = value
        _SLASHING_DETECTED.set(int(value))

    async def on_new_slot(self, slot: int, _: bool) -> None:
        # Update validator statuses one slot before the next epoch starts
        # (before duties are updated)
        slots_per_epoch = self.beacon_chain.spec.SLOTS_PER_EPOCH
        if slot % slots_per_epoch == slots_per_epoch - 1:
            self.task_manager.submit_task(self.update_validator_statuses())

    async def handle_slashing_event(
        self,
        event: SchemaBeaconAPI.BeaconNodeEvent,
    ) -> None:
        our_validator_indices = {
            validator.index
            for validator in self.active_validators + self.pending_validators
        }

        if isinstance(event, SchemaBeaconAPI.AttesterSlashingEvent):
            slashed_validator_indices = {
                int(i) for i in event.attestation_1.attesting_indices
            } & {int(i) for i in event.attestation_2.attesting_indices}
            our_slashed_indices = slashed_validator_indices & our_validator_indices

            if len(our_slashed_indices) > 0:
                self.slashing_detected = True
                self.logger.critical(
                    f"Slashing detected for validator indices {our_slashed_indices}",
                )
            self.logger.info(
                f"Processed attester slashing event affecting validator indices {slashed_validator_indices}",
            )
        elif isinstance(event, SchemaBeaconAPI.ProposerSlashingEvent):
            slashed_validator_index = int(event.signed_header_1.message.proposer_index)
            if slashed_validator_index in our_validator_indices:
                self.slashing_detected = True
                self.logger.critical(
                    f"Slashing detected for validator index {slashed_validator_index}",
                )
            self.logger.info(
                f"Processed proposer slashing event affecting validator index {slashed_validator_index}",
            )
        else:
            raise NotImplementedError(f"Unexpected event type {type(event)}")

    async def _update_validator_statuses(self, minimal_update: bool = False) -> None:
        """
        With minimal_update enabled, this function only fetches the slashed,
        active and pending validators in order to return as quickly as possible.
        """

        self.logger.debug("Updating validator statuses")

        remote_signer_pubkeys = set(await self.remote_signer.get_public_keys())

        slashed_validators = await self.multi_beacon_node.get_validators(
            ids=list(remote_signer_pubkeys),
            statuses=SLASHED_STATUSES,
        )

        if len(slashed_validators) > 0:
            self.slashing_detected = True
            self.logger.critical(
                f"Slashed validators detected while updating validator statuses. Slashed validators: {slashed_validators}",
            )

        self.active_validators = await self.multi_beacon_node.get_validators(
            ids=list(remote_signer_pubkeys),
            statuses=ACTIVE_STATUSES,
        )
        active_pubkeys = {v.pubkey for v in self.active_validators}

        self.pending_validators = await self.multi_beacon_node.get_validators(
            ids=list(remote_signer_pubkeys - active_pubkeys),
            statuses=PENDING_STATUSES,
        )
        pending_pubkeys = {v.pubkey for v in self.pending_validators}

        if len(active_pubkeys | pending_pubkeys) == 0:
            self.logger.warning("No active or pending validators detected")

        if minimal_update:
            return

        self.exited_validators = await self.multi_beacon_node.get_validators(
            ids=list(remote_signer_pubkeys - active_pubkeys - pending_pubkeys),
            statuses=EXITED_STATUSES,
        )
        exited_pubkeys = {v.pubkey for v in self.exited_validators}

        self.withdrawal_validators = await self.multi_beacon_node.get_validators(
            ids=list(
                remote_signer_pubkeys
                - active_pubkeys
                - pending_pubkeys
                - exited_pubkeys
            ),
            statuses=WITHDRAWAL_STATUSES,
        )
        withdrawal_pubkeys = {v.pubkey for v in self.withdrawal_validators}

        # Pubkeys not known on the beacon chain (not deposited to yet)
        known_pubkeys = (
            active_pubkeys | pending_pubkeys | exited_pubkeys | withdrawal_pubkeys
        )
        unknown_pubkeys = remote_signer_pubkeys - known_pubkeys

        self.logger.debug(
            f"Updated validator statuses."
            f" {len(active_pubkeys)} active,"
            f" {len(pending_pubkeys)} pending,"
            f" {len(exited_pubkeys)} exited,"
            f" {len(withdrawal_pubkeys)} withdrawal,"
            f" {len(unknown_pubkeys)} unknown.",
        )
        _VALIDATORS_COUNT.labels(status="unknown").set(len(unknown_pubkeys))
        _VALIDATORS_COUNT.labels(status="pending").set(len(pending_pubkeys))
        _VALIDATORS_COUNT.labels(status="active").set(len(active_pubkeys))
        _VALIDATORS_COUNT.labels(status="exited").set(len(exited_pubkeys))
        _VALIDATORS_COUNT.labels(status="withdrawal").set(len(withdrawal_pubkeys))

    async def update_validator_statuses(self) -> None:
        # Calls self._update_validator_statuses, retrying until it succeeds, with backoff

        # Backoff parameters
        initial_delay = 1.0  # Starting delay between API calls
        max_delay = 10.0  # Maximum delay between API calls
        current_delay = initial_delay

        while True:
            try:
                await self._update_validator_statuses()
                break
            except Exception as e:
                _ERRORS_METRIC.labels(
                    error_type=ErrorType.VALIDATOR_STATUS_UPDATE.value
                ).inc()
                self.logger.error(
                    f"Failed to update validator statuses: {e!r}",
                    exc_info=self.logger.isEnabledFor(logging.DEBUG),
                )

                # Wait for the current delay before retrying again
                await asyncio.sleep(current_delay)

                # Increase the delay for the next iteration, up to the max
                current_delay = min(current_delay * 2, max_delay)
