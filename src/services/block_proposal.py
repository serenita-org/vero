import asyncio
import time
from collections import defaultdict
from types import TracebackType
from typing import Self, Unpack

from opentelemetry import trace
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
)
from remerkleable.complex import Container

from observability import ErrorType, HandledRuntimeError
from schemas import SchemaBeaconAPI, SchemaRemoteSigner
from services.validator_duty_service import (
    ValidatorDuty,
    ValidatorDutyService,
    ValidatorDutyServiceOptions,
)
from spec.utils import encode_graffiti


class BlockProposalService(ValidatorDutyService):
    def __init__(self, **kwargs: Unpack[ValidatorDutyServiceOptions]) -> None:
        super().__init__(**kwargs)

        # Proposer duty by epoch
        self.proposer_duties: defaultdict[int, set[SchemaBeaconAPI.ProposerDuty]] = (
            defaultdict(set)
        )
        self.proposer_duties_dependent_roots: dict[int, str] = dict()

        self.randao_reveal_cache: dict[int, str] = dict()

    async def __aenter__(self) -> Self:
        try:
            duties, dependent_roots = self.duty_cache.load_proposer_duties()
            self.proposer_duties = defaultdict(set, duties)
            self.proposer_duties_dependent_roots = dependent_roots
        except Exception as e:
            self.logger.debug(f"Failed to load duties from cache: {e}")
        finally:
            # The cached duties may be stale - call update_duties even if
            # we loaded duties from cache
            self.task_manager.create_task(self.update_duties())

        self.task_manager.create_task(self.prepare_beacon_proposer())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            self.duty_cache.cache_proposer_duties(
                duties=self.proposer_duties,
                dependent_roots=self.proposer_duties_dependent_roots,
            )
        except Exception as e:
            self.logger.warning(f"Failed to cache duties: {e}")

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

    def has_upcoming_duty(self) -> bool:
        next_duty_slot = self.next_duty_slot
        if next_duty_slot is None:
            return False

        return next_duty_slot <= self.beacon_chain.current_slot + 3

    def duty_for_slot(self, slot: int) -> SchemaBeaconAPI.ProposerDuty | None:
        duty_epoch = slot // self.beacon_chain.SLOTS_PER_EPOCH
        slot_proposer_duties = [
            duty for duty in self.proposer_duties[duty_epoch] if int(duty.slot) == slot
        ]
        if len(slot_proposer_duties) == 0:
            return None

        if len(slot_proposer_duties) != 1:
            raise RuntimeError(
                f"Unexpected number of proposer duties ({len(slot_proposer_duties)}): {slot_proposer_duties}"
            )

        return next(d for d in slot_proposer_duties)

    def has_duty_for_slot(self, slot: int) -> bool:
        return self.duty_for_slot(slot) is not None

    async def on_new_slot(self, slot: int, is_new_epoch: bool) -> None:
        # Wait until any block proposals for this slot finish before
        # doing anything else
        await self.propose_block(slot=slot)

        # Prepare for block proposals due in the next slot
        duty_for_next_slot = self.duty_for_slot(slot + 1)
        if duty_for_next_slot:
            await self._fetch_randao_reveal(duty=duty_for_next_slot)
            # Call the `prepare_beacon_proposer` endpoint one more time
            # just before a block proposal is scheduled to decrease
            # the chances of the fee recipient being set incorrectly,
            # e.g., due to a beacon node restarting.
            await self.prepare_beacon_proposer()

        if self.cli_args.use_external_builder:
            self.task_manager.create_task(self.register_validators(current_slot=slot))

        # At the start of every epoch, update duties
        # and prepare the connected beacon nodes for
        # block proposals.
        if is_new_epoch:
            self.task_manager.create_task(super().update_duties())
            self.task_manager.create_task(self.prepare_beacon_proposer())

    async def handle_head_event(self, event: SchemaBeaconAPI.HeadEvent, _: str) -> None:
        if (
            event.current_duty_dependent_root
            not in self.proposer_duties_dependent_roots.values()
        ):
            self.logger.info(
                "Head event duty dependent root mismatch -> updating duties",
            )
            self.task_manager.create_task(super().update_duties())

    def _prune_duties(self) -> None:
        current_epoch = self.beacon_chain.current_epoch
        for epoch in list(self.proposer_duties.keys()):
            if epoch < current_epoch:
                del self.proposer_duties[epoch]

        for epoch in list(self.proposer_duties_dependent_roots.keys()):
            if epoch < current_epoch:
                del self.proposer_duties_dependent_roots[epoch]

    async def _update_duties(self) -> None:
        _validator_indices = (
            self.validator_status_tracker_service.active_or_pending_indices
        )
        if len(_validator_indices) == 0:
            self.logger.warning(
                "Not updating proposer duties - no active or pending validators",
            )
            return

        current_epoch = self.beacon_chain.current_epoch
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

            current_slot = self.beacon_chain.current_slot  # Cache property value
            self.proposer_duties[epoch] = {
                d
                for d in fetched_duties
                if int(d.slot) >= current_slot
                and int(d.validator_index) in _validator_indices
            }

            for duty in sorted(self.proposer_duties[epoch], key=lambda d: int(d.slot)):
                self.logger.info(
                    f"Upcoming block proposal duty at slot {duty.slot} for validator {duty.validator_index}",
                )

            self.logger.debug(
                f"Updated duties for epoch {epoch} -> {len(self.proposer_duties[epoch])}",
            )

        self._prune_duties()

    async def prepare_beacon_proposer(self) -> None:
        self.logger.debug("Calling prepare_beacon_proposer")

        our_validators = (
            self.validator_status_tracker_service.active_validators
            + self.validator_status_tracker_service.pending_validators
        )

        if len(our_validators) == 0:
            return

        # Default to values provided via the CLI arguments unless overridden
        # via the Keymanager API
        default_fee_recipient = self.cli_args.fee_recipient

        await self.multi_beacon_node.prepare_beacon_proposer(
            data=[
                {
                    "validator_index": str(v.index),
                    "fee_recipient": default_fee_recipient
                    if not self.keymanager.enabled
                    else self.keymanager.pubkey_to_fee_recipient_override.get(
                        v.pubkey, default_fee_recipient
                    ),
                }
                for v in our_validators
            ],
        )

    async def register_validators(self, current_slot: int) -> None:
        _batch_size = 512

        active_and_pending_validators = (
            self.validator_status_tracker_service.active_validators
            + self.validator_status_tracker_service.pending_validators
        )

        # Registers a subset of validators every slot
        # based on their index to spread the
        # registrations across the epoch
        slots_per_epoch = self.beacon_chain.SLOTS_PER_EPOCH
        validators_to_register = [
            v
            for v in active_and_pending_validators
            if v.index % slots_per_epoch == current_slot % slots_per_epoch
        ]

        _timestamp = int(time.time())

        # Default to values provided via the CLI arguments unless overridden
        # via the Keymanager API
        default_fee_recipient = self.cli_args.fee_recipient
        default_gas_limit = str(self.cli_args.gas_limit)

        for i in range(0, len(validators_to_register), _batch_size):
            validator_batch = validators_to_register[i : i + _batch_size]

            try:
                responses = await asyncio.gather(
                    *[
                        self.signature_provider.sign(
                            message=SchemaRemoteSigner.ValidatorRegistrationSignableMessage(
                                validator_registration=SchemaRemoteSigner.ValidatorRegistration(
                                    fee_recipient=default_fee_recipient
                                    if not self.keymanager.enabled
                                    else self.keymanager.pubkey_to_fee_recipient_override.get(
                                        v.pubkey, default_fee_recipient
                                    ),
                                    gas_limit=default_gas_limit
                                    if not self.keymanager.enabled
                                    else self.keymanager.pubkey_to_gas_limit_override.get(
                                        v.pubkey, default_gas_limit
                                    ),
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
                self.metrics.errors_c.labels(error_type=ErrorType.SIGNATURE.value).inc()
                self.logger.exception(
                    f"Failed to get signature for validator registrations: {e!r}",
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

    async def _fetch_randao_reveal(self, duty: SchemaBeaconAPI.ProposerDuty) -> None:
        self.logger.debug(f"Fetching RANDAO reveal for slot {duty.slot}")

        slot = int(duty.slot)
        epoch = slot // self.beacon_chain.SLOTS_PER_EPOCH

        _, randao_reveal, _ = await self.signature_provider.sign(
            message=SchemaRemoteSigner.RandaoRevealSignableMessage(
                fork_info=self.beacon_chain.get_fork_info(slot=slot),
                randao_reveal=SchemaRemoteSigner.RandaoReveal(
                    epoch=str(epoch),
                ),
            ),
            identifier=duty.pubkey,
        )
        self.randao_reveal_cache[slot] = randao_reveal

    async def _get_randao_reveal(
        self, slot: int, duty: SchemaBeaconAPI.ProposerDuty
    ) -> str:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}._get_randao_reveal",
        ):
            # Try to get it from the cache - it should be pre-populated
            # in the slot before a proposal is due
            if slot in self.randao_reveal_cache:
                return self.randao_reveal_cache.pop(slot)

            self.logger.warning(
                f"Failed to get RANDAO reveal for slot {slot} from cache"
            )

            # We failed to retrieve the value from the cache, fall back to
            # fetching it on-demand
            try:
                await self._fetch_randao_reveal(duty=duty)
            except Exception as e:
                self.logger.exception(
                    f"Failed to get RANDAO reveal: {e!r}",
                )
                raise HandledRuntimeError(
                    errors_counter=self.metrics.errors_c,
                    error_type=ErrorType.BLOCK_PRODUCE,
                ) from None
            else:
                return self.randao_reveal_cache.pop(slot)

    async def _produce_block(
        self, slot: int, duty: SchemaBeaconAPI.ProposerDuty, randao_reveal: str
    ) -> tuple[
        Container,
        SchemaRemoteSigner.BeaconBlockHeader,
        SchemaBeaconAPI.ProduceBlockV3Response,
    ]:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}._produce_block",
        ):
            graffiti = self.cli_args.graffiti
            if self.keymanager.enabled:
                kmgr_graffiti_str = self.keymanager.pubkey_to_graffiti_override.get(
                    duty.pubkey, None
                )
                if kmgr_graffiti_str is not None:
                    self.logger.info(
                        f"Using Keymanager-provided graffiti: {kmgr_graffiti_str}"
                    )
                    graffiti = encode_graffiti(kmgr_graffiti_str)

            try:
                (
                    block_contents_or_blinded_block,
                    full_response,
                ) = await self.multi_beacon_node.produce_block_v3(
                    slot=slot,
                    graffiti=graffiti,
                    builder_boost_factor=self.cli_args.builder_boost_factor,
                    randao_reveal=randao_reveal,
                )
            except Exception as e:
                self.logger.exception(
                    f"Failed to produce block: {e!r}",
                )
                raise HandledRuntimeError(
                    errors_counter=self.metrics.errors_c,
                    error_type=ErrorType.BLOCK_PRODUCE,
                ) from None
            else:
                if full_response.execution_payload_blinded:
                    beacon_block = block_contents_or_blinded_block
                else:
                    beacon_block = block_contents_or_blinded_block.block

                block_header = SchemaRemoteSigner.BeaconBlockHeader(
                    slot=str(beacon_block.slot),
                    proposer_index=str(beacon_block.proposer_index),
                    parent_root=str(beacon_block.parent_root),
                    state_root=str(beacon_block.state_root),
                    body_root="0x" + beacon_block.body.hash_tree_root().hex(),
                )

                return beacon_block, block_header, full_response

    async def _sign_block(
        self,
        slot: int,
        duty: SchemaBeaconAPI.ProposerDuty,
        block_header: SchemaRemoteSigner.BeaconBlockHeader,
        block_version: SchemaRemoteSigner.BeaconBlockVersion,
    ) -> str:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}._sign_block",
        ):
            try:
                _, signature, _ = await self.signature_provider.sign(
                    message=SchemaRemoteSigner.BeaconBlockV2SignableMessage(
                        fork_info=self.beacon_chain.get_fork_info(slot=slot),
                        beacon_block=SchemaRemoteSigner.BeaconBlock(
                            version=block_version,
                            block_header=block_header,
                        ),
                    ),
                    identifier=duty.pubkey,
                )
            except Exception as e:
                self.logger.exception(
                    f"Failed to get signature for block: {e!r}",
                )
                raise HandledRuntimeError(
                    errors_counter=self.metrics.errors_c, error_type=ErrorType.SIGNATURE
                ) from None
            else:
                return signature

    async def _publish_block(
        self,
        slot: int,
        full_response: SchemaBeaconAPI.ProduceBlockV3Response,
        signature: str,
        beacon_block: Container,
    ) -> None:
        self.logger.info(f"Publishing block for slot {slot}")
        self.metrics.duty_submission_time_h.labels(
            duty=ValidatorDuty.BLOCK_PROPOSAL.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}._publish_block",
        ):
            try:
                if full_response.execution_payload_blinded:
                    # Blinded block
                    await self.multi_beacon_node.publish_blinded_block_v2(
                        fork_version=full_response.version,
                        signed_blinded_beacon_block=SchemaBeaconAPI.SignedBeaconBlock(
                            message=full_response.data,
                            signature=signature,
                        ),
                    )
                else:
                    await self.multi_beacon_node.publish_block_v2(
                        fork_version=full_response.version,
                        signed_beacon_block_contents=SchemaBeaconAPI.BlockContentsSigned(
                            signed_block=SchemaBeaconAPI.SignedBeaconBlock(
                                message=full_response.data["block"],
                                signature=signature,
                            ),
                            kzg_proofs=full_response.data["kzg_proofs"],
                            blobs=full_response.data["blobs"],
                        ),
                    )
            except Exception as e:
                self.logger.exception(
                    f"Failed to publish block for slot {slot}: {e!r}",
                )
                raise HandledRuntimeError(
                    errors_counter=self.metrics.errors_c,
                    error_type=ErrorType.BLOCK_PUBLISH,
                ) from None
            else:
                self.logger.info(
                    f"Published block for slot {slot}, root 0x{beacon_block.hash_tree_root().hex()}",
                )
                self.metrics.vc_published_blocks_c.inc()

    async def _propose_block(
        self, slot: int, duty: SchemaBeaconAPI.ProposerDuty
    ) -> None:
        self.logger.info(f"Proposing block for slot {slot}")
        self._last_slot_duty_started_for = slot
        self.metrics.duty_start_time_h.labels(
            duty=ValidatorDuty.BLOCK_PROPOSAL.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

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
            name=f"{self.__class__.__name__}._propose_block",
            context=trace.set_span_in_context(span=NonRecordingSpan(span_ctx)),
            attributes={"beacon_chain.slot": slot},
        ):
            randao_reveal = await self._get_randao_reveal(slot=slot, duty=duty)

            beacon_block, block_header, full_response = await self._produce_block(
                slot=slot, duty=duty, randao_reveal=randao_reveal
            )

            signature = await self._sign_block(
                slot=slot,
                duty=duty,
                block_header=block_header,
                block_version=SchemaRemoteSigner.BeaconBlockVersion[
                    full_response.version.value.upper()
                ],
            )

            await self._publish_block(
                slot=slot,
                full_response=full_response,
                signature=signature,
                beacon_block=beacon_block,
            )

    async def propose_block(self, slot: int) -> None:
        if (
            self.validator_status_tracker_service.slashing_detected
            and not self.cli_args.disable_slashing_detection
        ):
            raise RuntimeError("Slashing detected, not producing block")

        if slot <= self._last_slot_duty_started_for:
            raise RuntimeError(
                f"Not producing block for slot {slot} (already started producing a block for slot {self._last_slot_duty_started_for})",
            )

        if slot != self.beacon_chain.current_slot:
            raise RuntimeError(
                f"Invalid slot for block proposal: {slot}. Current slot: {self.beacon_chain.current_slot}"
            )

        duty = self.duty_for_slot(slot=slot)
        if duty is None:
            self.logger.debug(f"No remaining proposer duties for slot {slot}")
            return

        epoch = slot // self.beacon_chain.SLOTS_PER_EPOCH
        self.proposer_duties[epoch].remove(duty)

        try:
            await self._propose_block(slot=slot, duty=duty)
        finally:
            self._last_slot_duty_completed_for = slot
