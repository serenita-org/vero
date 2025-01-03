import asyncio
import datetime
import logging
from collections import defaultdict
from typing import Unpack

import pytz
from opentelemetry import trace
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
)
from prometheus_client import Counter

from observability import ErrorType, get_shared_metrics
from schemas import SchemaBeaconAPI, SchemaRemoteSigner
from services.validator_duty_service import (
    ValidatorDuty,
    ValidatorDutyService,
    ValidatorDutyServiceOptions,
)
from spec.block import BeaconBlockHeader

_VC_PUBLISHED_BLOCKS = Counter(
    "vc_published_blocks",
    "Successfully published blocks",
)
_VC_PUBLISHED_BLOCKS.reset()
(_ERRORS_METRIC,) = get_shared_metrics()


class BlockProposalService(ValidatorDutyService):
    def __init__(self, **kwargs: Unpack[ValidatorDutyServiceOptions]) -> None:
        super().__init__(**kwargs)

        # Give a bit more headroom for block proposals since they are rare and valuable.
        # If there's less than this many seconds remaining until the next
        # block proposal duty, shutdown is deferred until the duty is completed.
        self._shutdown_defer_interval = 6

        # Proposer duty by epoch
        self.proposer_duties: defaultdict[int, set[SchemaBeaconAPI.ProposerDuty]] = (
            defaultdict(set)
        )
        self.proposer_duties_dependent_roots: dict[int, str] = dict()

    def start(self) -> None:
        self.scheduler.add_job(
            self.update_duties, id=f"{self.__class__.__name__}.update_duties"
        )
        self.scheduler.add_job(
            self.prepare_beacon_proposer,
            id=f"{self.__class__.__name__}.prepare_beacon_proposer",
        )
        if self.cli_args.use_external_builder:
            self.scheduler.add_job(
                self.register_validators,
                id=f"{self.__class__.__name__}.register_validators",
            )

    @property
    def next_duty_slot(self) -> int | None:
        # In case a duty for the current slot has not finished yet, it is still
        # considered the next duty slot
        if self.has_ongoing_duty:
            return self._last_slot_duty_started_for

        current_slot = self.beacon_chain.current_slot
        min_duty_slots_per_epoch = (
            min(
                (
                    int(d.slot)
                    for d in duties
                    if int(d.slot) > self._last_slot_duty_started_for
                    and int(d.slot) > current_slot
                ),
                default=None,
            )
            for duties in self.proposer_duties.values()
            if duties
        )
        return min(
            (slot for slot in min_duty_slots_per_epoch if slot is not None),
            default=None,
        )

    @property
    def next_duty_run_time(self) -> datetime.datetime | None:
        next_duty_slot = self.next_duty_slot
        if next_duty_slot is None:
            return None

        return self.beacon_chain.get_datetime_for_slot(next_duty_slot)

    async def handle_head_event(self, event: SchemaBeaconAPI.HeadEvent) -> None:
        if (
            event.current_duty_dependent_root
            not in self.proposer_duties_dependent_roots.values()
        ) and len(self.proposer_duties_dependent_roots) > 0:
            self.logger.info(
                "Head event duty dependent root mismatch -> updating duties",
            )
            self.scheduler.add_job(
                self.update_duties,
                id=f"{self.__class__.__name__}.update_duties",
                replace_existing=True,
            )

    def _prune_duties(self) -> None:
        current_epoch = self.beacon_chain.current_epoch
        for epoch in list(self.proposer_duties.keys()):
            if epoch < current_epoch:
                del self.proposer_duties[epoch]

        for epoch in list(self.proposer_duties_dependent_roots.keys()):
            if epoch < current_epoch:
                del self.proposer_duties_dependent_roots[epoch]

    async def _update_duties(self) -> None:
        if not self.validator_status_tracker_service.any_active_or_pending_validators:
            self.logger.warning(
                "Not updating proposer duties - no active or pending validators",
            )
            return

        current_epoch = self.beacon_chain.current_epoch

        _validator_indices = [
            v.index
            for v in self.validator_status_tracker_service.active_validators
            + self.validator_status_tracker_service.pending_validators
        ]

        for epoch in (current_epoch, current_epoch + 1):
            self.logger.debug(f"Updating proposer duties for epoch {epoch}")

            response = await self.multi_beacon_node.get_proposer_duties(
                epoch=epoch,
            )
            fetched_duties = response.data

            self.proposer_duties_dependent_roots[epoch] = response.dependent_root
            self.logger.debug(
                f"Dependent root for proposer duties for epoch {epoch} - {response.dependent_root}",
            )

            current_slot = self.beacon_chain.current_slot
            self.proposer_duties[epoch] = set()
            for duty in fetched_duties:
                duty_slot = int(duty.slot)
                if duty_slot < current_slot:
                    continue
                if int(duty.validator_index) in _validator_indices:
                    self.proposer_duties[epoch].add(duty)

                    self.logger.info(
                        f"Upcoming block proposal duty at slot {duty_slot} for validator {duty.validator_index}",
                    )

                    self.scheduler.add_job(
                        self.propose_block,
                        "date",
                        next_run_time=self.beacon_chain.get_datetime_for_slot(
                            slot=duty_slot,
                        ),
                        kwargs=dict(slot=duty_slot),
                        id=f"{self.__class__.__name__}.propose_block-slot-{duty_slot}",
                        replace_existing=True,
                    )

            self.logger.debug(
                f"Updated duties for epoch {epoch} -> {len(self.proposer_duties[epoch])}",
            )

        self._prune_duties()

    async def _prepare_beacon_proposer(self) -> None:
        self.logger.debug("Calling prepare beacon proposer")

        our_indices = [
            v.index
            for v in self.validator_status_tracker_service.active_validators
            + self.validator_status_tracker_service.pending_validators
        ]

        if len(our_indices) == 0:
            return

        await self.multi_beacon_node.prepare_beacon_proposer(
            data=[
                {
                    "validator_index": str(val_idx),
                    "fee_recipient": self.cli_args.fee_recipient,
                }
                for val_idx in our_indices
            ],
        )

    async def prepare_beacon_proposer(self) -> None:
        # TODO we have a lot of functions like this one, where we try something,
        # and schedule the next run time while catching exceptions and retrying
        # earlier than planned if an exception occurs. See if we can abstract
        # this away to reduce duplicate code.
        next_run_time = None
        try:
            await self._prepare_beacon_proposer()
        except Exception as e:
            self.logger.error(
                f"Failed to prepare beacon proposer: {e!r}",
                exc_info=self.logger.isEnabledFor(logging.DEBUG),
            )
            next_run_time = datetime.datetime.now(tz=pytz.UTC) + datetime.timedelta(
                seconds=1,
            )
        finally:
            # Schedule the next prepare_beacon_proposer call
            if next_run_time is None:
                next_run_time = self.beacon_chain.get_datetime_for_slot(
                    slot=(self.beacon_chain.current_epoch + 1)
                    * self.beacon_chain.spec.SLOTS_PER_EPOCH,
                )
            self.logger.debug(
                f"Next prepare_beacon_proposer job run time: {next_run_time}",
            )
            self.scheduler.add_job(
                self.prepare_beacon_proposer,
                "date",
                next_run_time=next_run_time,
                id=f"{self.__class__.__name__}.prepare_beacon_proposer",
                replace_existing=True,
            )

    async def _register_validators(self) -> None:
        _batch_size = 512

        active_and_pending_validators = (
            self.validator_status_tracker_service.active_validators
            + self.validator_status_tracker_service.pending_validators
        )

        # Registers a subset of validators every slot
        # based on their index to spread the
        # registrations across the epoch
        current_slot = self.beacon_chain.current_slot
        slots_per_epoch = self.beacon_chain.spec.SLOTS_PER_EPOCH
        validators_to_register = [
            v
            for v in active_and_pending_validators
            if v.index % slots_per_epoch == current_slot % slots_per_epoch
        ]

        _timestamp = int(datetime.datetime.now(tz=pytz.UTC).timestamp())

        for i in range(0, len(validators_to_register), _batch_size):
            validator_batch = validators_to_register[i : i + _batch_size]

            try:
                responses = await asyncio.gather(
                    *[
                        self.remote_signer.sign(
                            message=SchemaRemoteSigner.ValidatorRegistrationSignableMessage(
                                validator_registration=SchemaRemoteSigner.ValidatorRegistration(
                                    fee_recipient=self.cli_args.fee_recipient,
                                    gas_limit=str(self.cli_args.gas_limit),
                                    timestamp=str(_timestamp),
                                    pubkey=v.pubkey,
                                ),
                            ),
                            identifier=v.pubkey,
                        )
                        for v in validator_batch
                    ],
                )
            except Exception as e:
                _ERRORS_METRIC.labels(error_type=ErrorType.SIGNATURE.value).inc()
                self.logger.error(
                    f"Failed to get signature for validator registrations: {e!r}",
                    exc_info=self.logger.isEnabledFor(logging.DEBUG),
                )
                continue

            await self.multi_beacon_node.register_validator(
                signed_registrations=[
                    (msg.validator_registration, sig) for msg, sig, _ in responses
                ],
            )

            self.logger.info(
                f"Published validator registrations, count: {len(validator_batch)}"
            )

    async def register_validators(self) -> None:
        next_run_time = None
        try:
            await self._register_validators()
        except Exception as e:
            self.logger.error(
                f"Failed to register validators: {e!r}",
                exc_info=self.logger.isEnabledFor(logging.DEBUG),
            )
            # On registration errors we retry every 60 seconds
            next_run_time = datetime.datetime.now(tz=pytz.UTC) + datetime.timedelta(
                seconds=60,
            )
        finally:
            # Schedule the next register_validators call
            # The job runs every slot, and inside the job,
            # a subset of validators is selected (validator index // 32)
            # and registered with external builders.
            # This way we don't to request too many
            # signatures at once (when running large numbers of validators).
            if next_run_time is None:
                next_run_time = self.beacon_chain.get_datetime_for_slot(
                    slot=self.beacon_chain.current_slot + 1,
                )
            self.logger.debug(f"Next register_validators job run time: {next_run_time}")
            self.scheduler.add_job(
                self.register_validators,
                "date",
                next_run_time=next_run_time,
                id=f"{self.__class__.__name__}.register_validators",
                replace_existing=True,
            )

    async def propose_block(self, slot: int) -> None:
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
            name=f"{self.__class__.__name__}.propose_block",
            context=trace.set_span_in_context(span=NonRecordingSpan(span_ctx)),
            attributes={"beacon_chain.slot": slot},
        ):
            if self.validator_status_tracker_service.slashing_detected:
                raise RuntimeError("Slashing detected, not producing block")

            if slot <= self._last_slot_duty_started_for:
                self.logger.debug(
                    f"Not producing block for slot {slot} (already started producing a block for slot {self._last_slot_duty_started_for})",
                )
                return
            if slot != self.beacon_chain.current_slot:
                _ERRORS_METRIC.labels(
                    error_type=ErrorType.OTHER.value,
                ).inc()
                self.logger.error(
                    f"Invalid slot for block proposal: {slot}. Current slot: {self.beacon_chain.current_slot}"
                )
                return

            epoch = slot // self.beacon_chain.spec.SLOTS_PER_EPOCH
            slot_proposer_duties = {
                duty for duty in self.proposer_duties[epoch] if int(duty.slot) == slot
            }

            for duty in slot_proposer_duties:
                self.proposer_duties[epoch].remove(duty)

            if len(slot_proposer_duties) == 0:
                self.logger.debug(f"No remaining proposer duties for slot {slot}")
                return

            if len(slot_proposer_duties) != 1:
                raise ValueError(
                    f"Unexpected number of proposer duties ({len(slot_proposer_duties)}): {slot_proposer_duties}"
                )

            duty = slot_proposer_duties.pop()

            self.logger.info(f"Producing block for slot {slot}")
            self._last_slot_duty_started_for = slot
            self._duty_start_time_metric.labels(
                duty=ValidatorDuty.BLOCK_PROPOSAL.value,
            ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

            with self.tracer.start_as_current_span(
                name=f"{self.__class__.__name__}.sign_randao",
            ):
                try:
                    _, randao_reveal, _ = await self.remote_signer.sign(
                        message=SchemaRemoteSigner.RandaoRevealSignableMessage(
                            fork_info=self.beacon_chain.get_fork_info(slot=slot),
                            randao_reveal=SchemaRemoteSigner.RandaoReveal(
                                epoch=int(epoch),
                            ),
                        ),
                        identifier=duty.pubkey,
                    )
                except Exception as e:
                    _ERRORS_METRIC.labels(
                        error_type=ErrorType.SIGNATURE.value,
                    ).inc()
                    self.logger.error(
                        f"Failed to get signature for RANDAO reveal: {e!r}",
                        exc_info=self.logger.isEnabledFor(logging.DEBUG),
                    )
                    self._last_slot_duty_completed_for = slot
                    raise

            with self.tracer.start_as_current_span(
                name=f"{self.__class__.__name__}.produce_block",
            ):
                try:
                    (
                        beacon_block,
                        full_response,
                    ) = await self.multi_beacon_node.produce_block_v3(
                        slot=slot,
                        graffiti=self.cli_args.graffiti,
                        builder_boost_factor=self.cli_args.builder_boost_factor,
                        randao_reveal=randao_reveal,
                    )
                except Exception as e:
                    _ERRORS_METRIC.labels(
                        error_type=ErrorType.BLOCK_PRODUCE.value,
                    ).inc()
                    self.logger.error(
                        f"Failed to produce block: {e!r}",
                        exc_info=self.logger.isEnabledFor(logging.DEBUG),
                    )
                    self._last_slot_duty_completed_for = slot
                    raise

            beacon_block_header = BeaconBlockHeader(
                slot=beacon_block.slot,
                proposer_index=beacon_block.proposer_index,
                parent_root=beacon_block.parent_root,
                state_root=beacon_block.state_root,
                body_root=beacon_block.body.hash_tree_root(),
            )

            with self.tracer.start_as_current_span(
                name=f"{self.__class__.__name__}.sign_block",
            ):
                try:
                    _, signature, _ = await self.remote_signer.sign(
                        message=SchemaRemoteSigner.BeaconBlockV2SignableMessage(
                            fork_info=self.beacon_chain.get_fork_info(slot=slot),
                            beacon_block=SchemaRemoteSigner.BeaconBlock(
                                version=SchemaRemoteSigner.BeaconBlockVersion[
                                    full_response.version.value.upper()
                                ],
                                block_header=beacon_block_header.to_obj(),
                            ),
                        ),
                        identifier=duty.pubkey,
                    )
                except Exception as e:
                    _ERRORS_METRIC.labels(
                        error_type=ErrorType.SIGNATURE.value,
                    ).inc()
                    self.logger.error(
                        f"Failed to get signature for block: {e!r}",
                        exc_info=self.logger.isEnabledFor(logging.DEBUG),
                    )
                    self._last_slot_duty_completed_for = slot
                    raise

            self.logger.info(
                f"Publishing block for slot {slot}, root 0x{beacon_block.hash_tree_root().hex()}",
            )
            self._duty_submission_time_metric.labels(
                duty=ValidatorDuty.BLOCK_PROPOSAL.value,
            ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

            with self.tracer.start_as_current_span(
                name=f"{self.__class__.__name__}.publish_block",
            ):
                try:
                    if not full_response.execution_payload_blinded:
                        await self.multi_beacon_node.publish_block_v2(
                            block_version=full_response.version,
                            block=beacon_block,
                            blobs=full_response.data.get("blobs", []),
                            kzg_proofs=full_response.data.get("kzg_proofs", []),
                            signature=signature,
                        )
                    else:
                        # Blinded block
                        await self.multi_beacon_node.publish_blinded_block_v2(
                            block_version=full_response.version,
                            block=beacon_block,
                            signature=signature,
                        )
                except Exception as e:
                    _ERRORS_METRIC.labels(
                        error_type=ErrorType.BLOCK_PUBLISH.value,
                    ).inc()
                    self.logger.error(
                        f"Failed to publish block for slot {slot}: {e!r}",
                        exc_info=self.logger.isEnabledFor(logging.DEBUG),
                    )
                    raise
                else:
                    self.logger.info(
                        f"Published block for slot {slot}, root 0x{beacon_block.hash_tree_root().hex()}",
                    )

                    _VC_PUBLISHED_BLOCKS.inc()
                finally:
                    self._last_slot_duty_completed_for = slot
