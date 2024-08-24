import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from prometheus_client import Gauge

from providers import BeaconChain, MultiBeaconNode, RemoteSigner
from schemas import SchemaBeaconAPI, SchemaValidator
from schemas.validator import (
    ACTIVE_STATUSES,
    PENDING_STATUSES,
    SLASHED_STATUSES,
)

_VALIDATORS_COUNT = Gauge(
    "validator_status",
    "Amount of validators per status",
    labelnames=["status"],
)
_SLASHING_DETECTED = Gauge(
    "slashing_detected",
    "1 if any of the connected validators have been slashed, 0 otherwise",
)
_SLASHING_DETECTED.set(0)


class ValidatorStatusTrackerService:
    def __init__(
        self,
        multi_beacon_node: MultiBeaconNode,
        beacon_chain: BeaconChain,
        remote_signer: RemoteSigner,
        scheduler: AsyncIOScheduler,
    ):
        self.multi_beacon_node = multi_beacon_node
        self.beacon_chain = beacon_chain
        self.remote_signer = remote_signer

        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.getLogger().level)
        self.scheduler = scheduler

        self._slashing_detected = False

        self.active_validators: list[SchemaValidator.ValidatorIndexPubkey] = []
        self.pending_validators: list[SchemaValidator.ValidatorIndexPubkey] = []

    async def initialize(self):
        # Call the internal _update function explicitly at initialization time.
        # If we fail to retrieve our validator statuses, it doesn't make sense
        # to continue initializing the validator client since we don't know
        # which validators to retrieve duties for.
        await self._update_validator_statuses()
        self.scheduler.add_job(self.update_validator_statuses)

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

    def handle_slashing_event(
        self,
        event: SchemaBeaconAPI.AttesterSlashingEvent
        | SchemaBeaconAPI.ProposerSlashingEvent,
    ):
        our_validator_indices = {
            validator.index
            for validator in self.active_validators + self.pending_validators
        }

        if isinstance(event, SchemaBeaconAPI.AttesterSlashingEvent):
            slashed_validator_indices = set(
                event.attestation_1.attesting_indices
            ) & set(event.attestation_2.attesting_indices)
            our_slashed_indices = slashed_validator_indices & our_validator_indices

            if len(our_slashed_indices) > 0:
                self.slashing_detected = True
                self.logger.error(
                    f"Slashing detected for validator indices {our_slashed_indices}"
                )
            self.logger.info(
                f"Processed attester slashing event affecting validator indices {slashed_validator_indices}"
            )
        elif isinstance(event, SchemaBeaconAPI.ProposerSlashingEvent):
            slashed_validator_index = event.signed_header_1.message.proposer_index
            if slashed_validator_index in our_validator_indices:
                self.slashing_detected = True
                self.logger.error(
                    f"Slashing detected for validator index {slashed_validator_index}"
                )
            self.logger.info(
                f"Processed proposer slashing event affecting validator index {slashed_validator_index}"
            )
        else:
            raise NotImplementedError(f"Unexpected event type {type(event)}")

    async def _update_validator_statuses(self):
        self.logger.debug("Updating validator statuses")

        remote_signer_pubkeys = set(await self.remote_signer.get_public_keys())

        slashed_validators = await self.multi_beacon_node.get_validators(
            ids=list(remote_signer_pubkeys), statuses=SLASHED_STATUSES
        )

        if len(slashed_validators) > 0:
            self.slashing_detected = True
            self.logger.error(
                f"Slashed validators detected while updating validator statuses. Slashed validators: {slashed_validators}"
            )

        self.active_validators = await self.multi_beacon_node.get_validators(
            ids=list(remote_signer_pubkeys), statuses=ACTIVE_STATUSES
        )
        active_pubkeys = {v.pubkey for v in self.active_validators}

        self.pending_validators = await self.multi_beacon_node.get_validators(
            ids=list(remote_signer_pubkeys - active_pubkeys), statuses=PENDING_STATUSES
        )
        pending_pubkeys = {v.pubkey for v in self.pending_validators}

        # Pubkeys with no active/pending validator
        other_status_pubkeys = {
            pk
            for pk in remote_signer_pubkeys
            if pk not in active_pubkeys | pending_pubkeys
        }

        self.logger.debug(
            f"Updated validator statuses."
            f" {len(active_pubkeys)} active,"
            f" {len(pending_pubkeys)} pending,"
            f" {len(other_status_pubkeys)} others."
        )
        _VALIDATORS_COUNT.labels(status="active").set(len(active_pubkeys))
        _VALIDATORS_COUNT.labels(status="pending").set(len(pending_pubkeys))
        _VALIDATORS_COUNT.labels(status="other").set(len(other_status_pubkeys))

        if len(self.active_validators + self.pending_validators) == 0:
            self.logger.warning("No active or pending validators detected")

    async def update_validator_statuses(self):
        try:
            await self._update_validator_statuses()
        except Exception as e:
            self.logger.exception(e)

        # Schedule the update of validator statuses
        # one slot before the next epoch starts
        # (before duties are updated)
        next_run_time = self.beacon_chain.get_datetime_for_slot(
            slot=(self.beacon_chain.current_epoch + 2)
            * self.beacon_chain.spec.SLOTS_PER_EPOCH
            - 1
        )
        self.logger.debug(
            f"Next update_validator_statuses job run time: {next_run_time}"
        )
        self.scheduler.add_job(
            self.update_validator_statuses,
            "date",
            next_run_time=next_run_time,
            id="update_validator_statuses_job",
            replace_existing=True,
        )
