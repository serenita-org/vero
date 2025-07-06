import asyncio
import contextlib
import datetime
import time
from collections import defaultdict
from types import TracebackType
from typing import TYPE_CHECKING, Self, Unpack
from uuid import uuid4

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

from observability import ErrorType, get_shared_metrics
from schemas import SchemaBeaconAPI, SchemaRemoteSigner
from services.validator_duty_service import (
    ValidatorDuty,
    ValidatorDutyService,
    ValidatorDutyServiceOptions,
)
from spec.attestation import AttestationData, Checkpoint, SpecAttestation
from spec.common import (
    bytes_to_uint64,
    hash_function,
)
from spec.constants import TARGET_AGGREGATORS_PER_COMMITTEE

if TYPE_CHECKING:
    from remerkleable.settings import Root

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
_VC_ATTESTATION_CONSENSUS_CONTRIBUTIONS = CounterMetric(
    "vc_attestation_consensus_contributions",
    "Tracks how many times the attestation data's block root contributed to the attestation consensus by returning the same root as was emitted in the HeadEvent.",
    labelnames=["host"],
)
_VC_ATTESTATION_CONSENSUS_FAILURES = CounterMetric(
    "vc_attestation_consensus_failures",
    "Amount of attestation consensus failures",
)
_VC_ATTESTATION_CONSENSUS_FAILURES.reset()
(_ERRORS_METRIC,) = get_shared_metrics()

_PRODUCE_JOB_ID = "AttestationService.attest-slot-{duty_slot}"
_PRODUCE_ATTESTATION_DATA_SPAN_ID = "AttestationService.attest"


class AttestationService(ValidatorDutyService):
    def __init__(self, **kwargs: Unpack[ValidatorDutyServiceOptions]) -> None:
        super().__init__(**kwargs)

        # Attester duties by epoch
        self.attester_duties: defaultdict[
            int,
            set[SchemaBeaconAPI.AttesterDutyWithSelectionProof],
        ] = defaultdict(set)
        self.attester_duties_dependent_roots: dict[int, str] = dict()

        self.attestation_consensus_threshold = (
            self.cli_args.attestation_consensus_threshold
        )

        # Block root counter used for reaching consensus on attestation data to sign
        self.block_root_to_beacon_node_hosts: dict[str, set[str]] = defaultdict(set)
        self.block_root_to_consensus_reached_event: dict[str, asyncio.Event] = (
            defaultdict(asyncio.Event)
        )

        self.source_checkpoint_confirmation_cache: dict[int, Root] = dict()

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
            self.task_manager.submit_task(self.update_duties())

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
            func=self.attest,
            trigger="date",
            next_run_time=_produce_deadline,
            kwargs=dict(slot=slot),
            id=_PRODUCE_JOB_ID.format(duty_slot=slot),
            replace_existing=True,
        )

        # At the start of an epoch, update duties
        if is_new_epoch:
            self.task_manager.submit_task(super().update_duties())

    async def handle_head_event(
        self, event: SchemaBeaconAPI.HeadEvent, beacon_node_host: str
    ) -> None:
        if event.block in self._processed_head_block_roots:
            return

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
            self.task_manager.submit_task(super().update_duties())

        head_event_block_root_seen_before = (
            event.block in self.block_root_to_beacon_node_hosts
        )
        if head_event_block_root_seen_before:
            # We've already seen a head event for this block root and started
            # attesting
            # TODO make debug?
            self.logger.info(f"HeadEventConfirmation from {beacon_node_host}")
            self._update_consensus_on_block_root(
                bn_host=beacon_node_host,
                block_root=event.block,
            )
        else:
            # This is the first time we see the block root
            # TODO make debug?
            self.logger.info(
                f"Initial head event for slot {event.slot} received from {beacon_node_host}"
            )

            # Ignore the head event if we've already started attesting - it's either:
            # A) too late (entirely possible with a block that was proposed late / did not propagate well)
            # or B) we have already seen a different block root in a head event and started attesting using
            #       that (this is unlikely to happen but could happen e.g. in case of a reorg)
            if int(event.slot) <= self._last_slot_duty_started_for:
                # TODO make debug?
                #  on a late block and 5 beacon nodes, it will log 5x...
                #  ... ideally it would warn once and that's it but that would require
                #      another internal service variable...
                self.logger.info(
                    f"Ignoring late head event for slot {event.slot} from {beacon_node_host}"
                )
                return

            self._update_consensus_on_block_root(
                bn_host=beacon_node_host,
                block_root=event.block,
            )

            # Start attesting
            await self.attest(
                slot=int(event.slot),
                head_event=event,
                head_event_beacon_node_host=beacon_node_host,
            )

    def _update_consensus_on_block_root(self, bn_host: str, block_root: str) -> None:
        self.block_root_to_beacon_node_hosts[block_root].add(bn_host)

        if (
            len(self.block_root_to_beacon_node_hosts[block_root])
            >= self.attestation_consensus_threshold
        ):
            self.block_root_to_consensus_reached_event[block_root].set()

    async def _confirm_source_checkpoint(self, checkpoint: Checkpoint) -> None:
        checkpoint_htr = checkpoint.hash_tree_root()
        if (
            self.source_checkpoint_confirmation_cache.get(checkpoint.epoch)
            == checkpoint_htr
        ):
            # TODO remove logging/debug?
            self.logger.info("Source checkpoint confirmed from cache")
            return

        confirm_deadline_ts = self.beacon_chain.get_timestamp_for_slot(
            self.beacon_chain.current_slot + 1
        )
        try:
            await asyncio.wait_for(
                self.multi_beacon_node.confirm_source_checkpoint(checkpoint=checkpoint),
                timeout=confirm_deadline_ts - time.time(),
            )
            self.source_checkpoint_confirmation_cache[checkpoint.epoch] = checkpoint_htr
            self.logger.info("Source checkpoint confirmed!")
        except TimeoutError:
            self.logger.debug(f"Timed out confirming source checkpoint {checkpoint}")
            raise TimeoutError(
                f"Timed out confirming source checkpoint {checkpoint}"
            ) from None

    async def _produce_attestation_data_without_expected_root(
        self, slot: int
    ) -> AttestationData:
        att_data, bn_hosts = await asyncio.wait_for(
            self.multi_beacon_node.produce_attestation_data_without_head_event(
                slot=slot,
                committee_index=0,
            ),
            timeout=self.beacon_chain.get_timestamp_for_slot(slot + 1) - time.time(),
        )
        self.logger.debug(
            f"Produced attestation data without expected root using {bn_hosts}"
        )
        for bn_host in bn_hosts:
            _VC_ATTESTATION_CONSENSUS_CONTRIBUTIONS.labels(host=bn_host).inc()

        await self._confirm_source_checkpoint(checkpoint=att_data.source)
        return att_data

    async def _produce_attestation_data(
        self, slot: int, expected_block_root: str | None
    ) -> AttestationData:
        """
        Produces attestation data for the given slot.

        If an expected block root is provided, tries to reach consensus on it.
        If consensus can't be reached on the expected block root or no
        expected block root is provided, we wait for the required threshold of
        connected beacon nodes to agree on any head block root.
        """
        if expected_block_root is None:
            return await self._produce_attestation_data_without_expected_root(slot)

        # We have an expected block root; try to confirm it
        bn_host_with_initial_head = next(
            iter(self.block_root_to_beacon_node_hosts[expected_block_root])
        )

        # Fetch the full AttestationData while waiting for further head confirmations
        attestation_data_task = asyncio.create_task(
            self.multi_beacon_node.wait_for_attestation_data(
                expected_head_block_root=expected_block_root,
                slot=slot,
                committee_index=0,
            )
        )

        confirm_deadline_ts = (
            self.beacon_chain.get_timestamp_for_slot(slot)
            + 0.5 * self.beacon_chain.SECONDS_PER_SLOT
        )

        consensus_reached = self.block_root_to_consensus_reached_event[
            expected_block_root
        ]
        try:
            await asyncio.wait_for(
                consensus_reached.wait(), timeout=confirm_deadline_ts - time.time()
            )
        except TimeoutError:
            # Consensus was not reached on expected block root.
            # Fallback to behavior as if no head event block root was received.
            self.logger.warning(
                f"Consensus was not reached for slot {slot} and block root {expected_block_root} - falling back"
            )
            return await self._produce_attestation_data(
                slot=slot, expected_block_root=None
            )
        finally:
            # Clean up
            del self.block_root_to_consensus_reached_event[expected_block_root]
            contributing_bn_hosts = self.block_root_to_beacon_node_hosts.pop(
                expected_block_root, set()
            )
            self._processed_head_block_roots.append(expected_block_root)

        # Consensus was reached in time
        for bn_host in contributing_bn_hosts:
            _VC_ATTESTATION_CONSENSUS_CONTRIBUTIONS.labels(host=bn_host).inc()
            if bn_host != bn_host_with_initial_head:
                trace.get_current_span().add_event(
                    name="HeadEventConfirmation",
                    attributes={
                        "host.name": bn_host,
                    },
                )

        self.logger.info("Head decided, waiting for att data")
        att_data = await asyncio.wait_for(
            attestation_data_task,
            timeout=self.beacon_chain.get_timestamp_for_slot(slot + 1) - time.time(),
        )
        self.logger.info("Got att data")
        await self._confirm_source_checkpoint(checkpoint=att_data.source)
        return att_data

    async def attest(
        self,
        slot: int,
        head_event: SchemaBeaconAPI.HeadEvent | None = None,
        head_event_beacon_node_host: str | None = None,
    ) -> None:
        """
        We either
        a) call this function at the attestation deadline without a head_event
        or b) call this function when we see the first head event for the slot.

        If we see a head event in time, we cancel the scheduled function call
        at the attestation deadline.
        """
        if head_event is not None:
            # Cancel the scheduled job that would call this function
            # at 1/3 of the slot time if it has not yet been called
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

        epoch = slot // self.beacon_chain.SLOTS_PER_EPOCH
        slot_attester_duties = {
            duty for duty in self.attester_duties[epoch] if int(duty.slot) == slot
        }

        for duty in slot_attester_duties:
            self.attester_duties[epoch].remove(duty)

        if len(slot_attester_duties) == 0:
            self.logger.debug(f"No remaining attester duties for slot {slot}")
            return

        # We explicitly create a new span context
        # so this span doesn't get attached to some
        # previous context
        span_ctx = SpanContext(
            trace_id=slot,
            span_id=trace.INVALID_SPAN_ID,
            is_remote=False,
            trace_flags=TraceFlags(0x01),
        )
        span_attrs: dict[str, int | str] = {
            "beacon_chain.slot": slot,
        }
        if head_event:
            span_attrs["head_event.beacon_block_root"] = head_event.block
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.attest",
            context=trace.set_span_in_context(NonRecordingSpan(span_ctx)),
            attributes=span_attrs,
        ) as attest_span:
            if head_event is not None:
                attest_span.add_event(
                    name="HeadEvent",
                    attributes={
                        "host.name": head_event_beacon_node_host,
                    },
                )

            self.logger.debug(
                f"Attesting to slot {slot}, {len(slot_attester_duties)} duties",
            )
            self._last_slot_duty_started_for = slot
            self._duty_start_time_metric.labels(
                duty=ValidatorDuty.ATTESTATION.value,
            ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

            consensus_start = asyncio.get_running_loop().time()
            try:
                with self.tracer.start_as_current_span(
                    name=f"{self.__class__.__name__}.produce_attestation_data",
                ):
                    att_data = await self._produce_attestation_data(
                        slot=slot,
                        expected_block_root=head_event.block if head_event else None,
                    )
            except TimeoutError as e:
                self.logger.exception(
                    f"Failed to reach consensus on attestation data for slot {slot} among connected beacon nodes (head event: {head_event}): {e!r}",
                )
                _VC_ATTESTATION_CONSENSUS_FAILURES.inc()
                _ERRORS_METRIC.labels(
                    error_type=ErrorType.ATTESTATION_CONSENSUS.value,
                ).inc()
                self._last_slot_duty_completed_for = slot
                return
            else:
                consensus_time = asyncio.get_running_loop().time() - consensus_start
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

            # Ensure attestation data checkpoints are not in the future
            current_epoch = self.beacon_chain.current_epoch
            if any(
                cp.epoch > current_epoch for cp in (att_data.source, att_data.target)
            ):
                raise RuntimeError(
                    f"Checkpoint in returned attestation data is in the future:"
                    f"\nCurrent epoch: {current_epoch}"
                    f"\nAttestation data: {att_data}"
                )

            # Sign the attestation data
            attestations_objects_to_publish: list[
                SchemaBeaconAPI.SingleAttestation
            ] = []

            _fork_info = self.beacon_chain.get_fork_info(slot=slot)
            _fork_version = self.beacon_chain.current_fork_version

            pubkey_to_duty = {d.pubkey: d for d in slot_attester_duties}
            with self.tracer.start_as_current_span(
                name=f"{self.__class__.__name__}.sign_attestations",
            ) as sign_span:
                att_data_obj = att_data.to_obj()

                for coro in asyncio.as_completed(
                    [
                        self.signature_provider.sign(
                            message=SchemaRemoteSigner.AttestationSignableMessage(
                                fork_info=_fork_info,
                                attestation=att_data_obj,
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
                        self.logger.exception(
                            f"Failed to get signature for attestation for slot {slot}: {e!r}",
                        )
                        sign_span.set_status(Status(StatusCode.ERROR))
                        sign_span.record_exception(e)
                        continue

                    duty = pubkey_to_duty[pubkey]

                    # SingleAttestation object from the CL spec
                    attestations_objects_to_publish.append(
                        SchemaBeaconAPI.SingleAttestation(
                            committee_index=duty.committee_index,
                            attester_index=duty.validator_index,
                            data=att_data_obj,
                            signature=signature,
                        ),
                    )

            # Add the aggregation duty to the schedule *before*
            # publishing attestations so that any delays in publishing
            # do not affect the aggregation duty start time
            self.task_manager.submit_task(
                self.prepare_and_aggregate_attestations(
                    slot=slot,
                    att_data=att_data,
                    aggregator_duties=[
                        d for d in slot_attester_duties if d.is_aggregator
                    ],
                )
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
                        fork_version=_fork_version,
                    )
                except Exception as e:
                    _ERRORS_METRIC.labels(
                        error_type=ErrorType.ATTESTATION_PUBLISH.value,
                    ).inc()
                    self.logger.exception(
                        f"Failed to publish attestations for slot {att_data.slot}: {e!r}",
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
                finally:
                    self._last_slot_duty_completed_for = slot

    async def prepare_and_aggregate_attestations(
        self,
        slot: int,
        att_data: AttestationData,
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
        messages: list[SchemaRemoteSigner.AggregateAndProofSignableMessage]
        | list[SchemaRemoteSigner.AggregateAndProofV2SignableMessage],
        identifiers: list[str],
        fork_version: SchemaBeaconAPI.ForkVersion,
    ) -> None:
        signed_aggregate_and_proofs = []
        for msg, sig, _identifier in await self.signature_provider.sign_in_batches(  # type: ignore[misc]
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
                fork_version=fork_version,
            )
            _VC_PUBLISHED_AGGREGATE_ATTESTATIONS.inc(
                amount=len(signed_aggregate_and_proofs),
            )
        except Exception as e:
            _ERRORS_METRIC.labels(
                error_type=ErrorType.AGGREGATE_ATTESTATION_PUBLISH.value,
            ).inc()
            self.logger.exception(
                f"Failed to publish aggregate and proofs for slot {slot}: {e!r}",
            )

    async def aggregate_attestations(
        self,
        slot: int,
        att_data: AttestationData,
        aggregator_duties: list[SchemaBeaconAPI.AttesterDutyWithSelectionProof],
    ) -> None:
        if len(aggregator_duties) == 0:
            return

        self.logger.debug(
            f"Aggregating attestations for slot {slot}, {len(aggregator_duties)} duties",
        )
        self._duty_start_time_metric.labels(
            duty=ValidatorDuty.ATTESTATION_AGGREGATION.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

        committee_indices = {int(d.committee_index) for d in aggregator_duties}

        aggregate_count = 0
        self.logger.debug(
            f"Starting aggregate and proof sign-and-publish tasks for slot {att_data.slot}, committee indices: {committee_indices}",
        )

        _fork_info = self.beacon_chain.get_fork_info(slot=slot)
        _fork_version = self.beacon_chain.current_fork_version
        _sign_and_publish_tasks = []

        async for aggregate in self.multi_beacon_node.get_aggregate_attestations_v2(
            attestation_data=att_data,
            committee_indices=committee_indices,
        ):
            messages: (
                list[SchemaRemoteSigner.AggregateAndProofSignableMessage]
                | list[SchemaRemoteSigner.AggregateAndProofV2SignableMessage]
            ) = []
            identifiers = []
            for duty in aggregator_duties:
                if aggregate.committee_bits[int(duty.committee_index)]:
                    aggregate_count += 1
                    messages.append(
                        SchemaRemoteSigner.AggregateAndProofV2SignableMessage(  # type: ignore[arg-type]
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
            f"Published aggregate and proofs for slot {att_data.slot}, count: {aggregate_count}",
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
            _ERRORS_METRIC.labels(error_type=ErrorType.SIGNATURE.value).inc()
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

        self.task_manager.submit_task(
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
