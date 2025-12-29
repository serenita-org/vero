import asyncio
import contextlib
import datetime
import time
from collections import defaultdict
from types import TracebackType
from typing import Self, Unpack
from uuid import uuid4

import msgspec
from apscheduler.jobstores.base import JobLookupError

from observability import ErrorType
from providers import AttestationDataProvider
from schemas import SchemaBeaconAPI, SchemaRemoteSigner
from services.validator_duty_service import (
    ValidatorDuty,
    ValidatorDutyService,
    ValidatorDutyServiceOptions,
)
from spec.attestation import AttestationData, SpecAttestation
from spec.common import (
    bytes_to_uint64,
    hash_function,
)
from spec.constants import TARGET_AGGREGATORS_PER_COMMITTEE

_PRODUCE_JOB_ID = "AttestationService.attest_if_not_yet_attested-slot-{duty_slot}"


class AttestationService(ValidatorDutyService):
    def __init__(self, **kwargs: Unpack[ValidatorDutyServiceOptions]) -> None:
        super().__init__(**kwargs)

        self.attestation_data_provider = AttestationDataProvider(
            multi_beacon_node=self.multi_beacon_node,
            scheduler=self.scheduler,
        )

        # Attester duties by epoch
        self.attester_duties: defaultdict[
            int,
            set[SchemaBeaconAPI.AttesterDutyWithSelectionProof],
        ] = defaultdict(set)
        self.attester_duties_dependent_roots: dict[int, str] = dict()

    async def __aenter__(self) -> Self:
        try:
            duties, dependent_roots = self.duty_cache.load_attester_duties()
            self.attester_duties = defaultdict(set, duties)
            self.attester_duties_dependent_roots = dependent_roots
        except Exception as e:
            self.logger.debug(f"Failed to load duties from cache: {e}")
        finally:
            # The cached duties may be stale - call update_duties even if
            # we loaded duties from cache
            self.task_manager.create_task(self.update_duties())

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            self.duty_cache.cache_attester_duties(
                duties=self.attester_duties,
                dependent_roots=self.attester_duties_dependent_roots,
            )
        except Exception as e:
            self.logger.warning(f"Failed to cache duties: {e}")

    def has_duty_for_slot(self, slot: int) -> bool:
        epoch = slot // self.beacon_chain.SLOTS_PER_EPOCH
        return any(int(duty.slot) == slot for duty in self.attester_duties[epoch])

    async def on_new_slot(self, slot: int, is_new_epoch: bool) -> None:
        # Schedule attestation job at the attestation deadline in case
        # it is not triggered earlier by a new HeadEvent,
        # aiming to attest 1/3 into the slot at the latest.
        _produce_deadline = datetime.datetime.fromtimestamp(
            timestamp=self.beacon_chain.get_timestamp_for_slot(slot)
            + self.beacon_chain.SECONDS_PER_INTERVAL,
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

    async def handle_head_event(
        self, event: SchemaBeaconAPI.HeadEvent, beacon_node_host: str
    ) -> None:
        if any(
            root not in self.attester_duties_dependent_roots.values()
            for root in (
                event.previous_duty_dependent_root,
                event.current_duty_dependent_root,
            )
        ):
            self.logger.debug(
                "Head event duty dependent root mismatch -> updating duties",
            )
            self.task_manager.create_task(super().update_duties())

        # Ignore the head event if we've already started attesting - it's either:
        # A) too late (entirely possible with a block that was proposed late / did not propagate well)
        # or B) we have already seen a different block root in a head event and started attesting using
        #       that (this is unlikely to happen in practice but possible)
        if int(event.slot) <= self._last_slot_duty_started_for:
            self.logger.warning(
                f"Ignoring late head event for slot {event.slot} from {beacon_node_host}"
            )
            return

        await self.attest_if_not_yet_attested(slot=int(event.slot), head_event=event)

    def _get_duties_for_slot(
        self, slot: int
    ) -> set[SchemaBeaconAPI.AttesterDutyWithSelectionProof]:
        epoch = slot // self.beacon_chain.SLOTS_PER_EPOCH
        slot_attester_duties = {
            duty for duty in self.attester_duties[epoch] if int(duty.slot) == slot
        }

        for duty in slot_attester_duties:
            self.attester_duties[epoch].remove(duty)
        return slot_attester_duties

    async def _produce_attestation_data(
        self, slot: int, head_event: SchemaBeaconAPI.HeadEvent | None
    ) -> SchemaBeaconAPI.AttestationData:
        consensus_start = asyncio.get_running_loop().time()
        try:
            att_data = await asyncio.wait_for(
                self.attestation_data_provider.produce_attestation_data(
                    slot=slot,
                    head_event_block_root=head_event.block if head_event else None,
                ),
                timeout=self.beacon_chain.get_timestamp_for_slot(slot + 1)
                - time.time(),
            )
        except TimeoutError as e:
            self.logger.exception(
                f"Failed to reach consensus on attestation data for slot {slot} among connected beacon nodes ({head_event=}): {e!r}",
            )
            self.metrics.vc_attestation_consensus_failures_c.inc()
            self.metrics.errors_c.labels(
                error_type=ErrorType.ATTESTATION_CONSENSUS.value,
            ).inc()
            raise

        consensus_time = asyncio.get_running_loop().time() - consensus_start
        self.logger.debug(
            f"Reached consensus on attestation data in {consensus_time:.3f} seconds",
        )
        self.metrics.vc_attestation_consensus_time_h.observe(consensus_time)

        # Ensure attestation data checkpoints are not in the future
        current_epoch = self.beacon_chain.current_epoch
        if any(
            int(cp.epoch) > current_epoch for cp in (att_data.source, att_data.target)
        ):
            raise RuntimeError(
                f"Checkpoint in returned attestation data is in the future:"
                f"\nCurrent epoch: {current_epoch}"
                f"\nAttestation data: {att_data}"
            )

        return att_data

    async def _get_signed_attestations(
        self,
        slot: int,
        att_data: SchemaBeaconAPI.AttestationData,
        duties: set[SchemaBeaconAPI.AttesterDutyWithSelectionProof],
    ) -> list[SchemaBeaconAPI.SingleAttestation]:
        signed_attestations: list[SchemaBeaconAPI.SingleAttestation] = []

        pubkey_to_duty = {d.pubkey: d for d in duties}
        message = SchemaRemoteSigner.AttestationSignableMessage(
            fork_info=self.beacon_chain.get_fork_info(slot=slot),
            attestation=msgspec.to_builtins(att_data),
        )

        for coro in asyncio.as_completed(
            [
                self.signature_provider.sign(
                    message=message,
                    identifier=duty.pubkey,
                )
                for duty in duties
            ],
        ):
            try:
                message, signature, pubkey = await coro
            except Exception as e:
                self.metrics.errors_c.labels(
                    error_type=ErrorType.SIGNATURE.value,
                ).inc()
                self.logger.exception(
                    f"Failed to get signature for attestation for slot {slot}: {e!r}",
                )
                continue

            duty = pubkey_to_duty[pubkey]

            # SingleAttestation object from the CL spec
            signed_attestations.append(
                SchemaBeaconAPI.SingleAttestation(
                    committee_index=duty.committee_index,
                    attester_index=duty.validator_index,
                    data=att_data,
                    signature=signature,
                ),
            )

        return signed_attestations

    async def _publish_attestations(
        self,
        slot: int,
        att_data: SchemaBeaconAPI.AttestationData,
        signed_attestations: list[SchemaBeaconAPI.SingleAttestation],
    ) -> None:
        self.logger.debug(
            f"Publishing attestations for slot {slot}, count: {len(signed_attestations)}, head root: {att_data.beacon_block_root}",
        )
        self.metrics.duty_submission_time_h.labels(
            duty=ValidatorDuty.ATTESTATION.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

        try:
            await self.multi_beacon_node.publish_attestations(
                attestations=signed_attestations,
                fork_version=self.beacon_chain.current_fork_version,
            )
        except Exception as e:
            self.metrics.errors_c.labels(
                error_type=ErrorType.ATTESTATION_PUBLISH.value,
            ).inc()
            self.logger.exception(
                f"Failed to publish attestations for slot {att_data.slot}: {e!r}",
            )
        else:
            self.logger.info(
                f"Published attestations for slot {slot}, count: {len(signed_attestations)}, head root: {att_data.beacon_block_root}",
            )
            self.metrics.vc_published_attestations_c.inc(
                amount=len(signed_attestations),
            )

    async def _attest(
        self,
        slot: int,
        head_event: SchemaBeaconAPI.HeadEvent | None,
        duties: set[SchemaBeaconAPI.AttesterDutyWithSelectionProof],
    ) -> None:
        self.logger.debug(
            f"Attesting for {slot=}, {head_event=}, {len(duties)} duties",
        )
        self._last_slot_duty_started_for = slot
        self.metrics.duty_start_time_h.labels(
            duty=ValidatorDuty.ATTESTATION.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

        att_data = await self._produce_attestation_data(
            slot=slot, head_event=head_event
        )

        # Use the AttestationData later on for aggregation duties
        self.task_manager.create_task(
            self.prepare_and_aggregate_attestations(
                slot=slot,
                att_data=att_data,
                aggregator_duties=[d for d in duties if d.is_aggregator],
            )
        )

        # Sign the AttestationData
        signed_attestations = await self._get_signed_attestations(
            slot=slot,
            att_data=att_data,
            duties=duties,
        )

        # Published the signed attestations
        await self._publish_attestations(
            slot=slot, att_data=att_data, signed_attestations=signed_attestations
        )

    async def attest_if_not_yet_attested(
        self,
        slot: int,
        head_event: SchemaBeaconAPI.HeadEvent | None = None,
    ) -> None:
        """
        We either
        a) call this function at the attestation deadline without a head_event
        or b) call this function when we see the first head event for the slot.

        If we see a head event in time, we cancel the scheduled function call
        at the attestation deadline.
        """
        if head_event is not None:
            with contextlib.suppress(JobLookupError):
                self.scheduler.remove_job(
                    job_id=_PRODUCE_JOB_ID.format(duty_slot=slot),
                )

        if (
            self.validator_status_tracker_service.slashing_detected
            and not self.cli_args.disable_slashing_detection
        ):
            raise RuntimeError("Slashing detected, not attesting")

        if slot <= self._last_slot_duty_started_for:
            raise RuntimeError(
                f"Not attesting to slot {slot} - already started attesting to slot {self._last_slot_duty_started_for}"
            )

        if slot != self.beacon_chain.current_slot:
            raise RuntimeError(
                f"Invalid slot for attestation: {slot}. Current slot: {self.beacon_chain.current_slot}"
            )

        duties = self._get_duties_for_slot(slot)

        if len(duties) > 0:
            try:
                await self._attest(slot=slot, head_event=head_event, duties=duties)
            finally:
                self._last_slot_duty_completed_for = slot
        else:
            # Produce attestation data if there is an attester
            # duty scheduled for later in the epoch.
            # This ensures finality checkpoints are confirmed and cached early
            # into the epoch, even with a low number of active validators.
            epoch = slot // self.beacon_chain.SLOTS_PER_EPOCH
            if len(self.attester_duties[epoch]) > 0:
                _ = await asyncio.wait_for(
                    self.attestation_data_provider.produce_attestation_data(
                        slot=slot,
                        head_event_block_root=head_event.block if head_event else None,
                    ),
                    timeout=self.beacon_chain.get_timestamp_for_slot(slot + 1)
                    - time.time(),
                )

    async def prepare_and_aggregate_attestations(
        self,
        slot: int,
        att_data: SchemaBeaconAPI.AttestationData,
        aggregator_duties: list[SchemaBeaconAPI.AttesterDutyWithSelectionProof],
    ) -> None:
        # Schedule aggregated attestation at 2/3 of the slot
        aggregation_run_time = datetime.datetime.fromtimestamp(
            timestamp=self.beacon_chain.get_timestamp_for_slot(slot)
            + 2 * self.beacon_chain.SECONDS_PER_INTERVAL,
            tz=datetime.UTC,
        )
        self.scheduler.add_job(
            self.aggregate_attestations,
            kwargs=dict(
                slot=slot,
                att_data=att_data,
                aggregator_duties=aggregator_duties,
            ),
            next_run_time=aggregation_run_time,
            id=f"{self.__class__.__name__}.aggregate_attestations-slot-{slot}-{uuid4()}",
        )

    def _is_aggregator_by_committee_length(
        self,
        committee_length: int,
        slot_signature: bytes,
    ) -> bool:
        modulo = max(
            1,
            committee_length // TARGET_AGGREGATORS_PER_COMMITTEE,
        )
        return bytes_to_uint64(hash_function(slot_signature)[0:8]) % modulo == 0  # type: ignore[no-any-return]

    async def _sign_and_publish_aggregates(
        self,
        slot: int,
        messages: list[SchemaRemoteSigner.AggregateAndProofV2SignableMessage],
        identifiers: list[str],
        fork_version: SchemaBeaconAPI.ForkVersion,
    ) -> None:
        signed_aggregate_and_proofs = []
        for msg, sig, _identifier in await self.signature_provider.sign_in_batches(
            messages=messages,
            identifiers=identifiers,
        ):
            signed_aggregate_and_proofs.append((msg.aggregate_and_proof, sig))

        self.metrics.duty_submission_time_h.labels(
            duty=ValidatorDuty.ATTESTATION_AGGREGATION.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

        try:
            await self.multi_beacon_node.publish_aggregate_and_proofs(
                signed_aggregate_and_proofs=signed_aggregate_and_proofs,
                fork_version=fork_version,
            )
            self.metrics.vc_published_aggregate_attestations_c.inc(
                amount=len(signed_aggregate_and_proofs),
            )
        except Exception as e:
            self.metrics.errors_c.labels(
                error_type=ErrorType.AGGREGATE_ATTESTATION_PUBLISH.value,
            ).inc()
            self.logger.exception(
                f"Failed to publish aggregate and proofs for slot {slot}: {e!r}",
            )

    async def aggregate_attestations(
        self,
        slot: int,
        att_data: SchemaBeaconAPI.AttestationData,
        aggregator_duties: list[SchemaBeaconAPI.AttesterDutyWithSelectionProof],
    ) -> None:
        if len(aggregator_duties) == 0:
            return

        self.logger.debug(
            f"Aggregating attestations for slot {slot}, {len(aggregator_duties)} duties",
        )
        attestation_data_root = (
            "0x"
            + AttestationData.from_obj(msgspec.to_builtins(att_data))
            .hash_tree_root()
            .hex()
        )
        self.metrics.duty_start_time_h.labels(
            duty=ValidatorDuty.ATTESTATION_AGGREGATION.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

        committee_indices = {int(d.committee_index) for d in aggregator_duties}

        aggregate_count = 0
        self.logger.debug(
            f"Starting aggregate and proof sign-and-publish tasks, {slot=}, {committee_indices=}",
        )

        _fork_info = self.beacon_chain.get_fork_info(slot=slot)
        _fork_version = self.beacon_chain.current_fork_version
        _sign_and_publish_tasks = []

        async for aggregate in self.multi_beacon_node.get_aggregate_attestations_v2(
            attestation_data_root=attestation_data_root,
            slot=slot,
            committee_indices=committee_indices,
        ):
            messages: list[SchemaRemoteSigner.AggregateAndProofV2SignableMessage] = []
            identifiers = []
            for duty in aggregator_duties:
                if aggregate.committee_bits[int(duty.committee_index)]:
                    aggregate_count += 1
                    messages.append(
                        SchemaRemoteSigner.AggregateAndProofV2SignableMessage(
                            fork_info=_fork_info,
                            aggregate_and_proof=SpecAttestation.AggregateAndProofElectra(
                                aggregator_index=int(duty.validator_index),
                                aggregate=aggregate,
                                selection_proof=duty.selection_proof,
                            ).to_obj(),
                        )
                    )
                    identifiers.append(duty.pubkey)

            _sign_and_publish_tasks.append(
                asyncio.create_task(
                    self._sign_and_publish_aggregates(
                        slot=slot,
                        messages=messages,
                        identifiers=identifiers,
                        fork_version=_fork_version,
                    )
                )
            )

        await asyncio.gather(*_sign_and_publish_tasks)
        self.logger.info(
            f"Published aggregate and proofs for slot {slot}, count: {aggregate_count}",
        )

    async def _get_duties_with_selection_proofs(
        self, duties: list[SchemaBeaconAPI.AttesterDuty]
    ) -> list[SchemaBeaconAPI.AttesterDutyWithSelectionProof]:
        if len(duties) == 0:
            return []

        # Fork info for all slots in the same epoch will be the same
        _fork_slot = int(next(d.slot for d in duties))
        _fork_info = self.beacon_chain.get_fork_info(slot=_fork_slot)

        # Gather aggregation duty selection proofs
        try:
            signable_messages = []
            identifiers = []

            for duty in duties:
                signable_messages.append(
                    SchemaRemoteSigner.AggregationSlotSignableMessage(
                        fork_info=_fork_info,
                        aggregation_slot=SchemaRemoteSigner.Slot(slot=str(duty.slot)),
                    ),
                )
                identifiers.append(duty.pubkey)

            signatures = await self.signature_provider.sign_in_batches(
                messages=signable_messages,
                identifiers=identifiers,
            )
        except Exception as e:
            self.metrics.errors_c.labels(error_type=ErrorType.SIGNATURE.value).inc()
            self.logger.exception(
                f"Failed to get signatures for aggregation selection proofs: {e!r}",
            )
            raise

        pubkey_to_selection_proof = {
            pubkey: bytes.fromhex(sig[2:]) for _, sig, pubkey in signatures
        }

        duties_with_proofs = []
        for duty in duties:
            selection_proof = pubkey_to_selection_proof[duty.pubkey]
            is_aggregator = self._is_aggregator_by_committee_length(
                committee_length=int(duty.committee_length),
                slot_signature=selection_proof,
            )

            duties_with_proofs.append(
                SchemaBeaconAPI.AttesterDutyWithSelectionProof.from_duty(
                    duty=duty,
                    is_aggregator=is_aggregator,
                    selection_proof=selection_proof,
                )
            )

        # Prepare beacon node subnet subscriptions
        beacon_committee_subscriptions_data = [
            SchemaBeaconAPI.SubscribeToBeaconCommitteeSubnetRequestBody(
                validator_index=duty.validator_index,
                committee_index=duty.committee_index,
                committees_at_slot=duty.committees_at_slot,
                slot=duty.slot,
                is_aggregator=duty.is_aggregator,
            )
            for duty in duties_with_proofs
        ]

        self.task_manager.create_task(
            self.multi_beacon_node.prepare_beacon_committee_subscriptions(
                data=beacon_committee_subscriptions_data,
            ),
        )

        return duties_with_proofs

    def _prune_duties(self) -> None:
        current_epoch = self.beacon_chain.current_epoch
        for epoch in list(self.attester_duties.keys()):
            if epoch < current_epoch:
                del self.attester_duties[epoch]

        for epoch in list(self.attester_duties_dependent_roots.keys()):
            if epoch < current_epoch:
                del self.attester_duties_dependent_roots[epoch]

    async def _update_duties(self) -> None:
        _validator_indices = (
            self.validator_status_tracker_service.active_or_pending_indices
        )
        if len(_validator_indices) == 0:
            self.logger.warning(
                "Not updating attester duties - no active or pending validators",
            )
            return

        current_epoch = self.beacon_chain.current_epoch
        for epoch in (current_epoch, current_epoch + 1):
            self.logger.debug(f"Updating attester duties for epoch {epoch}")

            response = await self.multi_beacon_node.get_attester_duties(
                epoch=epoch,
                indices=_validator_indices,
            )
            self.logger.debug(
                f"Dependent root for attester duties for epoch {epoch} - {response.dependent_root}",
            )

            if response.dependent_root == self.attester_duties_dependent_roots.get(
                epoch,
                None,
            ):
                # We already processed these same duties
                self.logger.debug(
                    f"Skipping further processing of retrieved attester duties for epoch {epoch} - we already have duties with dependent root {self.attester_duties_dependent_roots.get(epoch)}",
                )
                continue

            self.attester_duties[epoch] = set()

            # For large amounts of validators, the `_get_duties_with_selection_proofs`
            # can take quite a while.
            # Run `_get_duties_with_selection_proofs` for the next couple of slots
            # first, and only worry about the rest of the duties once we are ready to
            # perform the duties that are due soon.
            current_slot = self.beacon_chain.current_slot
            duties_due_soon = []
            duties_due_later = []
            fetched_duties = response.data
            for duty in fetched_duties:
                duty_slot = int(duty.slot)
                if duty_slot < current_slot:
                    continue
                if duty_slot <= current_slot + 1:
                    duties_due_soon.append(duty)
                else:
                    duties_due_later.append(duty)

            for list_of_duties in (duties_due_soon, duties_due_later):
                for duty_with_proof in await self._get_duties_with_selection_proofs(
                    duties=list_of_duties,
                ):
                    self.attester_duties[epoch].add(duty_with_proof)

            self.logger.debug(
                f"Updated duties for epoch {epoch} -> {len(self.attester_duties[epoch])} duties",
            )

            # Only set the dependent root value once all duties for the epoch have been
            # successfully added. That way, if something fails while getting the
            # selection proofs, another attempt will be made later thanks to the
            # retry mechanism in `ValidatorDutyService.update_duties`
            self.attester_duties_dependent_roots[epoch] = response.dependent_root

        self._prune_duties()
