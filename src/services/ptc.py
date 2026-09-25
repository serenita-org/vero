import asyncio
import contextlib
import datetime
from collections import defaultdict
from types import TracebackType
from typing import Self, Unpack

import msgspec
from apscheduler.jobstores.base import JobLookupError
from spy_ssz import Fork

from observability import ErrorType
from schemas import SchemaBeaconAPI, SchemaRemoteSigner, SchemaShared
from services.validator_duty_service import (
    ValidatorDutyService,
    ValidatorDutyServiceOptions,
)
from spec import preset_types
from spec.common import get_slot_component_duration_ms

_PRODUCE_JOB_ID = "PtcService.attest_if_not_yet_attested-slot-{duty_slot}"


class PtcService(ValidatorDutyService):
    def __init__(self, **kwargs: Unpack[ValidatorDutyServiceOptions]) -> None:
        super().__init__(**kwargs)

        self._payload_attestation_due_s = (
            get_slot_component_duration_ms(
                basis_points=self.spec.PAYLOAD_ATTESTATION_DUE_BPS,
                slot_duration_ms=self.spec.SLOT_DURATION_MS,
            )
            / 1_000
        )

        # PTC duties by epoch
        self.ptc_duties: defaultdict[
            int,
            set[SchemaBeaconAPI.PtcDuty],
        ] = defaultdict(set)
        self.ptc_duties_dependent_roots: dict[int, str] = dict()

    async def __aenter__(self) -> Self:
        self.task_manager.create_task(self.update_duties())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    def has_duty_for_slot(self, slot: int) -> bool:
        epoch = slot // self.beacon_chain.SLOTS_PER_EPOCH
        return any(int(duty.slot) == slot for duty in self.ptc_duties[epoch])

    async def wait_for_duty_completion(self) -> None:
        # Not waiting for PTC duty completion during shutdown
        # since it:
        # - is not critical
        # - is not incentivized
        # - for those reasons shouldn't delay the shutdown process
        return

    async def on_new_slot(self, slot: int, is_new_epoch: bool) -> None:
        # Schedule attestation job at the attestation deadline in case
        # it is not triggered earlier by a new ExecutionPayloadAvailableEvent,
        # aiming to attest self._payload_attestation_due_s into the slot at the latest.
        _produce_deadline = datetime.datetime.fromtimestamp(
            timestamp=self.beacon_chain.get_timestamp_for_slot(slot)
            + self._payload_attestation_due_s,
            tz=datetime.UTC,
        )

        self.scheduler.add_job(
            func=self.attest_if_not_yet_attested,
            trigger="date",
            next_run_time=_produce_deadline,
            kwargs=dict(slot=slot),
            id=_PRODUCE_JOB_ID.format(duty_slot=slot),
            replace_existing=True,
        )

        # At the start of an epoch, update duties
        if is_new_epoch:
            self.task_manager.create_task(super().update_duties())

    async def handle_execution_payload_available_event(
        self, event: SchemaBeaconAPI.ExecutionPayloadAvailableEvent
    ) -> None:
        # Ignore the event if we've already started attesting
        if int(event.slot) <= self._last_slot_duty_started_for:
            self.logger.warning(f"Ignoring late EPA event for slot {event.slot}")
            return

        await self.attest_if_not_yet_attested(
            slot=int(event.slot),
            payload_available_event=event,
        )

    def _get_duties_for_slot(self, slot: int) -> set[SchemaBeaconAPI.PtcDuty]:
        epoch = slot // self.beacon_chain.SLOTS_PER_EPOCH
        slot_ptc_duties = {
            duty for duty in self.ptc_duties[epoch] if int(duty.slot) == slot
        }

        for duty in slot_ptc_duties:
            self.ptc_duties[epoch].remove(duty)
        return slot_ptc_duties

    async def _attest(
        self,
        slot: int,
        payload_available_event: SchemaBeaconAPI.ExecutionPayloadAvailableEvent | None,
        duties: set[SchemaBeaconAPI.PtcDuty],
    ) -> None:
        self.logger.debug(
            f"Attesting for {slot=}, {payload_available_event=}, {len(duties)} duties",
        )
        self._last_slot_duty_started_for = slot

        payload_att_data = (
            await self.multi_beacon_node.produce_payload_attestation_data(slot=slot)
        )

        if payload_att_data is None:
            # No block has been seen for the slot -> no payload attestation to cast
            return

        # Sign and publish as signed messages become available.
        message = SchemaRemoteSigner.PayloadAttestationSignableMessage(
            fork_info=self.beacon_chain.get_fork_info(slot=slot),
            payload_attestation_message=msgspec.Raw(payload_att_data.to_json()),
        )
        signing_coros = [
            self.signature_provider.sign(
                message=message,
                identifier=duty.pubkey,
            )
            for duty in duties
        ]

        signed_messages = []
        pubkey_to_duty = {d.pubkey: d for d in duties}
        for result in await asyncio.gather(*signing_coros, return_exceptions=True):
            if isinstance(result, BaseException):
                self.metrics.errors_c.labels(error_type=ErrorType.SIGNATURE.value).inc()
                self.logger.error(
                    f"Failed to get signature for PTC message for slot {slot}: {result!r}",
                    exc_info=result,
                )
                continue

            _msg, sig, pubkey = result
            duty = pubkey_to_duty[pubkey]
            signed_messages.append(
                preset_types(
                    Fork[self.beacon_chain.current_fork_version.name]
                ).payload_attestation_message(
                    validator_index=duty.validator_index,
                    data=payload_att_data,
                    signature=sig,
                ),
            )

        await self.multi_beacon_node.publish_payload_attestation_messages(
            messages=signed_messages,
            fork_version=self.beacon_chain.current_fork_version,
        )
        self.logger.info(
            f"Published PTC attestations for slot {slot}, count: {len(signed_messages)}",
        )
        # TODO metric - total count of published PTC messages - for the Vero overview
        #  Grafana dashboard
        #  + edit said dashboard

    async def attest_if_not_yet_attested(
        self,
        slot: int,
        payload_available_event: SchemaBeaconAPI.ExecutionPayloadAvailableEvent
        | None = None,
    ) -> None:
        """
        We either
        a) call this function at the PTC deadline without a payload_available_event
        or b) call this function when we see the first payload_available event for the slot.

        If we see an event in time, we cancel the scheduled function call
        at the PTC deadline.
        """
        if slot <= self._last_slot_duty_started_for:
            raise RuntimeError(
                f"Not attesting to slot {slot} - already started PTC attesting to slot {self._last_slot_duty_started_for}"
            )

        if slot != self.beacon_chain.current_slot:
            raise RuntimeError(
                f"Invalid slot for PTC attestation: {slot}. Current slot: {self.beacon_chain.current_slot}"
            )

        if payload_available_event is not None:
            with contextlib.suppress(JobLookupError):
                self.scheduler.remove_job(
                    job_id=_PRODUCE_JOB_ID.format(duty_slot=slot),
                )

        duties = self._get_duties_for_slot(slot)

        if len(duties) > 0:
            try:
                await self._attest(
                    slot=slot,
                    payload_available_event=payload_available_event,
                    duties=duties,
                )
            finally:
                self._last_slot_duty_completed_for = slot

    def _prune_duties(self) -> None:
        current_epoch = self.beacon_chain.current_epoch
        for epoch in list(self.ptc_duties.keys()):
            if epoch < current_epoch:
                del self.ptc_duties[epoch]

        for epoch in list(self.ptc_duties_dependent_roots.keys()):
            if epoch < current_epoch:
                del self.ptc_duties_dependent_roots[epoch]

    async def _update_duties(self) -> None:
        _validator_indices = (
            self.validator_status_tracker_service.active_or_pending_indices
        )
        if len(_validator_indices) == 0:
            self.logger.warning(
                "Not updating duties - no active or pending validators",
            )
            return

        if self.beacon_chain.current_fork_version != SchemaShared.ForkVersion.GLOAS:
            return

        current_epoch = self.beacon_chain.current_epoch
        for epoch in (current_epoch, current_epoch + 1):
            self.logger.debug(f"Updating PTC duties for epoch {epoch}")

            response = await self.multi_beacon_node.get_ptc_duties(
                epoch=epoch,
                indices=_validator_indices,
            )
            self.logger.debug(
                f"Dependent root for PTC duties for epoch {epoch} - {response.dependent_root}",
            )

            if response.dependent_root == self.ptc_duties_dependent_roots.get(
                epoch,
                None,
            ):
                # We already processed these same duties
                self.logger.debug(
                    f"Skipping further processing of retrieved PTC duties for epoch {epoch} - we already have duties with dependent root {self.ptc_duties_dependent_roots.get(epoch)}",
                )
                continue

            self.ptc_duties[epoch] = set(response.data)

            self.logger.debug(
                f"Updated duties for epoch {epoch} -> {len(self.ptc_duties[epoch])} duties",
            )

            # Only set the dependent root value once all duties for the epoch have been
            # successfully added. That way if something fails, another attempt will be
            # made later thanks to the retry mechanism in `ValidatorDutyService.update_duties`
            self.ptc_duties_dependent_roots[epoch] = response.dependent_root

        self._prune_duties()
