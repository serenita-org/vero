import asyncio
import contextlib
import datetime
import logging
from collections import defaultdict
from typing import Unpack

from apscheduler.jobstores.base import JobLookupError
from opentelemetry import trace
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    Status,
    StatusCode,
    TraceFlags,
)
from prometheus_client import Counter as CounterMetric
from prometheus_client import Histogram
from remerkleable.bitfields import Bitlist

from observability import ErrorType, get_shared_metrics
from providers.multi_beacon_node import AttestationConsensusFailure
from schemas import SchemaBeaconAPI, SchemaRemoteSigner
from services.validator_duty_service import (
    ValidatorDuty,
    ValidatorDutyService,
    ValidatorDutyServiceOptions,
)
from spec.attestation import AggregateAndProof, AttestationData
from spec.common import (
    MAX_VALIDATORS_PER_COMMITTEE,
    bytes_to_uint64,
    hash_function,
)

logging.basicConfig()

_VC_PUBLISHED_ATTESTATIONS = CounterMetric(
    "vc_published_attestations",
    "Successfully published attestations",
)
_VC_PUBLISHED_ATTESTATIONS.reset()
_VC_PUBLISHED_AGGREGATE_ATTESTATIONS = CounterMetric(
    "vc_published_aggregate_attestations",
    "Successfully published aggregate attestations",
)
_VC_PUBLISHED_AGGREGATE_ATTESTATIONS.reset()
_VC_ATTESTATION_CONSENSUS_TIME = Histogram(
    "vc_attestation_consensus_time",
    "Time it took to achieve consensus on the attestation beacon block root",
    buckets=[0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5, 0.75, 1, 2, 3],
)
_VC_ATTESTATION_CONSENSUS_FAILURES = CounterMetric(
    "vc_attestation_consensus_failures",
    "Amount of attestation consensus failures",
)
_VC_ATTESTATION_CONSENSUS_FAILURES.reset()
(_ERRORS_METRIC,) = get_shared_metrics()

_PRODUCE_JOB_ID = "attest_if_not_yet_job_for_slot_{duty_slot}"


class AttestationService(ValidatorDutyService):
    def __init__(self, **kwargs: Unpack[ValidatorDutyServiceOptions]) -> None:
        super().__init__(**kwargs)

        # Attester duties by epoch
        self.attester_duties: defaultdict[
            int,
            set[SchemaBeaconAPI.AttesterDutyWithSelectionProof],
        ] = defaultdict(set)
        self.attester_duties_dependent_roots: dict[int, str] = dict()

    def start(self) -> None:
        self.scheduler.add_job(self.update_duties)

    async def handle_head_event(self, event: SchemaBeaconAPI.HeadEvent) -> None:
        if (
            any(
                root not in self.attester_duties_dependent_roots.values()
                for root in (
                    event.previous_duty_dependent_root,
                    event.current_duty_dependent_root,
                )
            )
            and len(self.attester_duties_dependent_roots) > 0
        ):
            self.logger.info(
                "Head event duty dependent root mismatch -> updating duties",
            )
            self.scheduler.add_job(self.update_duties)
        await self.attest_if_not_yet_attested(slot=event.slot, head_event=event)

    async def attest_if_not_yet_attested(
        self,
        slot: int,
        head_event: SchemaBeaconAPI.HeadEvent | None = None,
    ) -> None:
        # We explicitly create a new span context
        # so this span doesn't get attached to some
        # previous context
        span_ctx = SpanContext(
            trace_id=slot,
            span_id=trace.INVALID_SPAN_ID,
            is_remote=False,
            trace_flags=TraceFlags(0x01),
        )
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.attest_if_not_yet_attested",
            context=trace.set_span_in_context(NonRecordingSpan(span_ctx)),
            attributes={"beacon_chain.slot": slot},
        ):
            if self.validator_status_tracker_service.slashing_detected:
                raise RuntimeError("Slashing detected, not attesting")

            if slot <= self._last_slot_duty_performed_for:
                self.logger.warning(
                    f"Not attesting to slot {slot} (already started attesting to slot {self._last_slot_duty_performed_for})",
                )
                return
            self._last_slot_duty_performed_for = slot

            epoch = slot // self.beacon_chain.spec.SLOTS_PER_EPOCH
            slot_attester_duties = {
                duty for duty in self.attester_duties[epoch] if duty.slot == slot
            }

            for duty in slot_attester_duties:
                self.attester_duties[epoch].remove(duty)

            if head_event is not None:
                # Cancel the scheduled job that would call this function
                # at 1/3 of the slot time if it has not yet been called
                with contextlib.suppress(JobLookupError):
                    self.scheduler.remove_job(
                        job_id=_PRODUCE_JOB_ID.format(duty_slot=slot),
                    )

            if len(slot_attester_duties) == 0:
                self.logger.debug(f"No remaining attester duties for slot {slot}")
                return

            self.logger.debug(
                f"Attesting to slot {slot}, {len(slot_attester_duties)} duties",
            )
            self._duty_start_time_metric.labels(
                duty=ValidatorDuty.ATTESTATION.value,
            ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

            # Deadline is set at 2/3 into the slot.
            # That is quite late into the slot, we do not want to attest that late.
            # Consensus on the latest head block is normally reached
            # much faster though.
            deadline = self.beacon_chain.get_datetime_for_slot(
                slot,
            ) + datetime.timedelta(
                seconds=2
                * int(self.beacon_chain.spec.SECONDS_PER_SLOT)
                / int(self.beacon_chain.spec.INTERVALS_PER_SLOT),
            )

            consensus_start = asyncio.get_event_loop().time()
            with self.tracer.start_as_current_span(
                name=f"{self.__class__.__name__}.produce_attestation_data",
            ):
                try:
                    att_data = await self.multi_beacon_node.produce_attestation_data(
                        deadline=deadline,
                        head_event=head_event,
                        slot=slot,
                        committee_index=0,
                    )
                except AttestationConsensusFailure as e:
                    self.logger.error(
                        f"Failed to produce attestation data: {e!r}",
                        exc_info=self.logger.isEnabledFor(logging.DEBUG),
                    )
                    _VC_ATTESTATION_CONSENSUS_FAILURES.inc()
                    _ERRORS_METRIC.labels(
                        error_type=ErrorType.ATTESTATION_CONSENSUS.value,
                    ).inc()
                    return

            consensus_time = asyncio.get_event_loop().time() - consensus_start
            self.logger.debug(
                f"Reached consensus on attestation data in {consensus_time:.3f} seconds",
            )
            _VC_ATTESTATION_CONSENSUS_TIME.observe(consensus_time)

            self.logger.debug(
                "Attestation data:"
                f"\nSource: {att_data.source}"
                f"\nTarget: {att_data.target}"
                f"\nHead: {att_data.beacon_block_root} (from head event: {head_event is not None})"
            )

            # Sign the attestation data
            attestations_objects_to_publish: list[dict] = []  # type: ignore[type-arg]

            def _att_data_for_committee_idx(
                _orig_att_data_obj: dict,  # type: ignore[type-arg]
                committee_index: int,
            ) -> dict:  # type: ignore[type-arg]
                # This updates the attestation data's index field
                # to the correct, committee-specific value.
                return {**_orig_att_data_obj, "index": str(committee_index)}

            _fork_info = self.beacon_chain.get_fork_info(slot=slot)
            pubkey_to_duty = {d.pubkey: d for d in slot_attester_duties}
            with self.tracer.start_as_current_span(
                name=f"{self.__class__.__name__}.sign_attestations",
            ) as sign_span:
                att_data_obj = att_data.to_obj()

                for coro in asyncio.as_completed(
                    [
                        self.remote_signer.sign(
                            message=SchemaRemoteSigner.AttestationSignableMessage(
                                fork_info=_fork_info,
                                attestation=_att_data_for_committee_idx(
                                    att_data_obj,
                                    duty.committee_index,
                                ),
                            ),
                            identifier=duty.pubkey,
                        )
                        for duty in slot_attester_duties
                    ],
                ):
                    try:
                        message, signature, pubkey = await coro
                    except Exception as e:
                        _ERRORS_METRIC.labels(
                            error_type=ErrorType.SIGNATURE.value,
                        ).inc()
                        self.logger.error(
                            f"Failed to get signature for attestation for slot {slot}: {e!r}",
                            exc_info=self.logger.isEnabledFor(logging.DEBUG),
                        )
                        sign_span.set_status(Status(StatusCode.ERROR))
                        sign_span.record_exception(e)
                        continue

                    duty = pubkey_to_duty[pubkey]

                    aggregation_bits = Bitlist[MAX_VALIDATORS_PER_COMMITTEE](
                        False for _ in range(duty.committee_length)
                    )
                    aggregation_bits[duty.validator_committee_index] = True

                    attestations_objects_to_publish.append(
                        dict(
                            aggregation_bits=aggregation_bits.to_obj(),
                            data=_att_data_for_committee_idx(
                                att_data_obj,
                                duty.committee_index,
                            ),
                            signature=signature,
                        ),
                    )

            # Add the aggregation duty to the schedule *before*
            # publishing attestations so that any delays in publishing
            # do not affect the aggregation duty start time
            self.scheduler.add_job(
                self.prepare_and_aggregate_attestations,
                kwargs=dict(
                    slot=slot,
                    att_data=att_data,
                    aggregator_duties=[
                        d for d in slot_attester_duties if d.is_aggregator
                    ],
                ),
            )

            self.logger.debug(
                f"Publishing attestations for slot {slot}, count: {len(attestations_objects_to_publish)}",
            )

            self._duty_submission_time_metric.labels(
                duty=ValidatorDuty.ATTESTATION.value,
            ).observe(self.beacon_chain.time_since_slot_start(slot=slot))
            with self.tracer.start_as_current_span(
                name=f"{self.__class__.__name__}.publish_attestations",
            ) as publish_span:
                try:
                    await self.multi_beacon_node.publish_attestations(
                        attestations=attestations_objects_to_publish,
                    )
                except Exception as e:
                    _ERRORS_METRIC.labels(
                        error_type=ErrorType.ATTESTATION_PUBLISH.value,
                    ).inc()
                    self.logger.error(
                        f"Failed to publish attestations for slot {att_data.slot}: {e!r}",
                        exc_info=self.logger.isEnabledFor(logging.DEBUG),
                    )
                    publish_span.set_status(Status(StatusCode.ERROR))
                    publish_span.record_exception(e)
                else:
                    self.logger.info(
                        f"Published attestations for slot {slot}, count: {len(attestations_objects_to_publish)}",
                    )

                    _VC_PUBLISHED_ATTESTATIONS.inc(
                        amount=len(attestations_objects_to_publish),
                    )

    def prepare_and_aggregate_attestations(
        self,
        slot: int,
        att_data: AttestationData,
        aggregator_duties: set[SchemaBeaconAPI.AttesterDutyWithSelectionProof],
    ) -> None:
        # Schedule aggregated attestation at 2/3 of the slot
        aggregation_run_time = self.beacon_chain.get_datetime_for_slot(
            slot,
        ) + datetime.timedelta(
            seconds=2
            * int(self.beacon_chain.spec.SECONDS_PER_SLOT)
            / int(self.beacon_chain.spec.INTERVALS_PER_SLOT),
        )
        self.scheduler.add_job(
            self.aggregate_attestations,
            kwargs=dict(
                slot=slot,
                att_data=att_data,
                aggregator_duties=aggregator_duties,
            ),
            next_run_time=aggregation_run_time,
        )

    def _is_aggregator_by_committee_length(
        self,
        committee_length: int,
        slot_signature: bytes,
    ) -> bool:
        modulo = max(
            1,
            committee_length // self.beacon_chain.spec.TARGET_AGGREGATORS_PER_COMMITTEE,
        )
        return bytes_to_uint64(hash_function(slot_signature)[0:8]) % modulo == 0  # type: ignore[no-any-return]

    async def _sign_and_publish_aggregates(
        self,
        slot: int,
        messages: list[SchemaRemoteSigner.AggregateAndProofSignableMessage],
        identifiers: list[str],
    ) -> None:
        signed_aggregate_and_proofs = []
        for msg, sig, _identifier in await self.remote_signer.sign_in_batches(
            messages=messages,
            identifiers=identifiers,
        ):
            signed_aggregate_and_proofs.append((msg.aggregate_and_proof, sig))

        self._duty_submission_time_metric.labels(
            duty=ValidatorDuty.ATTESTATION_AGGREGATION.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

        try:
            await self.multi_beacon_node.publish_aggregate_and_proofs(
                signed_aggregate_and_proofs=signed_aggregate_and_proofs,
            )
            _VC_PUBLISHED_AGGREGATE_ATTESTATIONS.inc(
                amount=len(signed_aggregate_and_proofs),
            )
        except Exception as e:
            _ERRORS_METRIC.labels(
                error_type=ErrorType.AGGREGATE_ATTESTATION_PUBLISH.value,
            ).inc()
            self.logger.error(
                f"Failed to publish aggregate and proofs for slot {slot}: {e!r}",
                exc_info=self.logger.isEnabledFor(logging.DEBUG),
            )

    async def aggregate_attestations(
        self,
        slot: int,
        att_data: AttestationData,
        aggregator_duties: set[SchemaBeaconAPI.AttesterDutyWithSelectionProof],
    ) -> None:
        if len(aggregator_duties) == 0:
            return

        self.logger.debug(
            f"Aggregating attestations for slot {slot}, {len(aggregator_duties)} duties",
        )
        self._duty_start_time_metric.labels(
            duty=ValidatorDuty.ATTESTATION_AGGREGATION.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

        committee_indices = {d.committee_index for d in aggregator_duties}

        aggregate_count = 0
        self.logger.debug(
            f"Starting aggregate and proof sign-and-publish tasks for slot {att_data.slot}",
        )

        _fork_info = self.beacon_chain.get_fork_info(slot=slot)
        _sign_and_publish_tasks = []
        async for aggregate in self.multi_beacon_node.get_aggregate_attestations(
            attestation_data=att_data,
            committee_indices=committee_indices,
        ):
            messages = []
            identifiers = []
            for duty in aggregator_duties:
                if duty.committee_index == aggregate.data.index:
                    aggregate_count += 1
                    messages.append(
                        SchemaRemoteSigner.AggregateAndProofSignableMessage(
                            fork_info=_fork_info,
                            aggregate_and_proof=AggregateAndProof(
                                aggregator_index=duty.validator_index,
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
                    )
                )
            )

        await asyncio.gather(*_sign_and_publish_tasks)
        self.logger.info(
            f"Published aggregate and proofs for slot {att_data.slot}, count: {aggregate_count}",
        )

    async def _prep_and_schedule_duties(
        self,
        duties: list[SchemaBeaconAPI.AttesterDuty],
    ) -> list[SchemaBeaconAPI.AttesterDutyWithSelectionProof]:
        if len(duties) == 0:
            return []

        # Fork info for all slots in the same epoch will be the same
        _fork_slot = next(d.slot for d in duties)
        _fork_info = self.beacon_chain.get_fork_info(slot=_fork_slot)

        # Schedule attestation job at the attestation deadline in case
        # it is not triggered earlier by a new HeadEvent
        for duty_slot in {duty.slot for duty in duties}:
            self.logger.debug(f"Adding attest_if_not_yet job for slot {duty_slot}")
            self.scheduler.add_job(
                self.attest_if_not_yet_attested,
                "date",
                next_run_time=self.beacon_chain.get_datetime_for_slot(slot=duty_slot)
                + datetime.timedelta(
                    seconds=int(self.beacon_chain.spec.SECONDS_PER_SLOT)
                    / int(self.beacon_chain.spec.INTERVALS_PER_SLOT),
                ),
                kwargs={"slot": duty_slot},
                id=_PRODUCE_JOB_ID.format(duty_slot=duty_slot),
                replace_existing=True,
            )

        # Gather aggregation duty selection proofs
        try:
            signable_messages = []
            identifiers = []

            for duty in duties:
                signable_messages.append(
                    SchemaRemoteSigner.AggregationSlotSignableMessage(
                        fork_info=_fork_info,
                        aggregation_slot=SchemaRemoteSigner.Slot(slot=duty.slot),
                    ),
                )
                identifiers.append(duty.pubkey)

            signatures = await self.remote_signer.sign_in_batches(
                messages=signable_messages,
                identifiers=identifiers,
            )
        except Exception as e:
            _ERRORS_METRIC.labels(error_type=ErrorType.SIGNATURE.value).inc()
            self.logger.error(
                f"Failed to get signatures for aggregation selection proofs: {e!r}",
                exc_info=self.logger.isEnabledFor(logging.DEBUG),
            )
            raise

        pubkey_to_selection_proof = {
            pubkey: bytes.fromhex(sig[2:]) for _, sig, pubkey in signatures
        }

        duties_with_proofs = []
        for duty in duties:
            selection_proof = pubkey_to_selection_proof[duty.pubkey]
            is_aggregator = self._is_aggregator_by_committee_length(
                committee_length=duty.committee_length,
                slot_signature=selection_proof,
            )

            duties_with_proofs.append(
                SchemaBeaconAPI.AttesterDutyWithSelectionProof(
                    **duty.model_dump(),
                    is_aggregator=is_aggregator,
                    selection_proof=selection_proof,
                ),
            )

        # Prepare beacon node subnet subscriptions for aggregation duties
        beacon_committee_subscriptions_data = [
            dict(
                validator_index=str(duty.validator_index),
                committee_index=str(duty.committee_index),
                committees_at_slot=str(duty.committees_at_slot),
                slot=str(duty.slot),
                is_aggregator=duty.is_aggregator,
            )
            for duty in duties_with_proofs
            if duty.is_aggregator
        ]

        self.scheduler.add_job(
            self.multi_beacon_node.prepare_beacon_committee_subscriptions,
            kwargs=dict(data=beacon_committee_subscriptions_data),
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
        if not self.validator_status_tracker_service.any_active_or_pending_validators:
            self.logger.warning(
                "Not updating attester duties - no active or pending validators",
            )
            return

        current_epoch = self.beacon_chain.current_epoch

        _validator_indices = [
            v.index
            for v in self.validator_status_tracker_service.active_validators
            + self.validator_status_tracker_service.pending_validators
        ]

        for epoch in (current_epoch, current_epoch + 1):
            self.logger.debug(f"Updating attester duties for epoch {epoch}")

            response = await self.multi_beacon_node.get_attester_duties(
                epoch=epoch,
                indices=_validator_indices,
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

            self.attester_duties_dependent_roots[epoch] = response.dependent_root
            self.logger.debug(
                f"Dependent root for attester duties for epoch {epoch} - {response.dependent_root}",
            )
            self.attester_duties[epoch] = set()

            # For large amounts of validators, the `_prep_and_schedule_duties`
            # can take quite a while since aggregation duty selection proofs
            # are computed in there.
            # Run `_prep_and_schedule_duties` for the next couple of slots first,
            # and only worry about the rest of the duties once we are ready to
            # perform the duties that are due soon.
            current_slot = self.beacon_chain.current_slot
            duties_due_soon = []
            duties_due_later = []
            fetched_duties = response.data
            for duty in fetched_duties:
                if duty.slot < current_slot:
                    continue
                if duty.slot <= current_slot + 1:
                    duties_due_soon.append(duty)
                else:
                    duties_due_later.append(duty)

            for list_of_duties in (duties_due_soon, duties_due_later):
                for duty_with_proof in await self._prep_and_schedule_duties(
                    duties=list_of_duties,
                ):
                    self.attester_duties[epoch].add(duty_with_proof)

            self.logger.debug(
                f"Updated duties for epoch {epoch} -> {len(self.attester_duties[epoch])}",
            )

        self._prune_duties()
