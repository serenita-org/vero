import asyncio
import contextlib
import time
from collections import defaultdict
from types import TracebackType
from typing import NamedTuple, Self, Unpack

from opentelemetry import trace
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
)
from spy_ssz import (
    ExecutionPayloadEnvelopeGloas,
    ObjectKind,
    SignedExecutionPayloadEnvelopeGloas,
)

from observability import ErrorType, HandledRuntimeError
from providers import BeaconNode, BidSelector
from providers._headers import ContentType
from schemas import SchemaBeaconAPI, SchemaRemoteSigner, SchemaShared
from services.validator_duty_service import (
    ValidatorDuty,
    ValidatorDutyService,
    ValidatorDutyServiceOptions,
)
from spec import BeaconBlock
from spec.common import get_slot_component_duration_ms
from spec.utils import encode_graffiti

# BUILDER_INDEX_SELF_BUILD = UINT64_MAX
BUILDER_INDEX_SELF_BUILD = 2**64 - 1


class BlockPublishResult(NamedTuple):
    block_root: str
    envelope_required: bool


class BlockProposalService(ValidatorDutyService):
    def __init__(self, **kwargs: Unpack[ValidatorDutyServiceOptions]) -> None:
        super().__init__(**kwargs)

        self.bid_selector = BidSelector(vero=self.vero)

        # Block production API requests "soft" time out half-way into the attestation
        # deadline (e.g. 2s for Ethereum, 0.83s for Gnosis Chain). This ensures
        # a single slow beacon node does not delay a block proposal too much.
        # If no block has been produced by the soft timeout, we wait indefinitely for
        # the first block to be produced by any beacon node, and propose that block.
        attestation_due_s = (
            get_slot_component_duration_ms(
                basis_points=self.spec.ATTESTATION_DUE_BPS,
                slot_duration_ms=self.spec.SLOT_DURATION_MS,
            )
            / 1_000
        )
        self._block_production_soft_timeout = 1 / 2 * attestation_due_s

        # Proposer duty by epoch
        self.proposer_duties: defaultdict[int, set[SchemaBeaconAPI.ProposerDuty]] = (
            defaultdict(set)
        )
        self.proposer_duties_dependent_roots: dict[int, str] = dict()

        self.randao_reveal_cache: dict[tuple[int, str], str] = dict()

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
            await self._fetch_randao_reveal(
                slot=slot + 1, pubkey=duty_for_next_slot.pubkey
            )
            # Call `prepare_beacon_proposer` and `register_validators` one more time
            # just before a block proposal is scheduled to decrease
            # the chances of the fee recipient being set incorrectly,
            # e.g., due to a beacon node restarting.
            await self.prepare_beacon_proposer()
            await self.register_validators(
                current_slot=slot,
                pubkeys_to_register=[duty_for_next_slot.pubkey],
            )
            # TODO
            await self.submit_proposer_preferences()
            # Pre-establish connections to builders
            # to avoid tcp+tls handshake overhead on the get-bid request
            await self.bid_selector.multi_builder.warm_connections()

        self.task_manager.create_task(self.register_validators(current_slot=slot))
        # TODO?
        # self.task_manager.create_task(self.submit_proposer_preferences())

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

            if epoch >= self.beacon_chain.GLOAS_FORK_EPOCH:
                response = await self.multi_beacon_node.get_proposer_duties_v2(
                    epoch=epoch,
                )
            else:
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
                self.bid_selector.proposal_slots.add(int(duty.slot))

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

    async def register_validators(
        self,
        current_slot: int,
        pubkeys_to_register: list[str] | None = None,
    ) -> None:
        if not self.cli_args.use_external_builder:
            return

        if self.beacon_chain.current_fork_version not in (
            SchemaShared.ForkVersion.ELECTRA,
            SchemaShared.ForkVersion.FULU,
        ):
            return

        _batch_size = 512

        active_and_pending_validators = (
            self.validator_status_tracker_service.active_validators
            + self.validator_status_tracker_service.pending_validators
        )

        if pubkeys_to_register is None:
            # Registers a subset of validators every slot
            # based on their index to spread the
            # registrations across the epoch
            slots_per_epoch = self.beacon_chain.SLOTS_PER_EPOCH
            pubkeys_to_register = [
                v.pubkey
                for v in active_and_pending_validators
                if v.index % slots_per_epoch == current_slot % slots_per_epoch
            ]

        _timestamp = int(time.time())

        # Default to values provided via the CLI arguments unless overridden
        # via the Keymanager API
        default_fee_recipient = self.cli_args.fee_recipient
        default_gas_limit = str(self.cli_args.gas_limit)

        for i in range(0, len(pubkeys_to_register), _batch_size):
            pubkey_batch = pubkeys_to_register[i : i + _batch_size]

            try:
                responses = await asyncio.gather(
                    *[
                        self.signature_provider.sign(
                            message=SchemaRemoteSigner.ValidatorRegistrationSignableMessage(
                                validator_registration=SchemaRemoteSigner.ValidatorRegistration(
                                    fee_recipient=default_fee_recipient
                                    if not self.keymanager.enabled
                                    else self.keymanager.pubkey_to_fee_recipient_override.get(
                                        pubkey, default_fee_recipient
                                    ),
                                    gas_limit=default_gas_limit
                                    if not self.keymanager.enabled
                                    else self.keymanager.pubkey_to_gas_limit_override.get(
                                        pubkey, default_gas_limit
                                    ),
                                    timestamp=str(_timestamp),
                                    pubkey=pubkey,
                                ),
                            ),
                            identifier=pubkey,
                        )
                        for pubkey in pubkey_batch
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
                f"Published validator registrations, count: {len(pubkey_batch)}"
            )

    async def submit_proposer_preferences(self) -> None:
        # TODO Ok this needs some reworking, it seems we should only send these
        # when expecting to propose soonish? so different from validator registrations

        # TODO we only really _need_ to broadcast this if we want to receive trusted
        #  bids.
        #  OR (!!!) indicate what target gas limit we want.

        # Default to values provided via the CLI arguments unless overridden
        # via the Keymanager API
        default_fee_recipient = self.cli_args.fee_recipient
        # TODO consider adding deprecating gas-limit CLI flag and replacing it with target-gas-limit
        default_target_gas_limit = str(self.cli_args.gas_limit)

        current_slot = self.beacon_chain.current_slot

        for epoch, proposer_duties in self.proposer_duties.items():
            signed_preferences = []
            _fork_info = self.beacon_chain.get_fork_info(
                slot=self.beacon_chain.SLOTS_PER_EPOCH * epoch
            )
            for duty in proposer_duties:
                if int(duty.slot) < current_slot:
                    continue
                # TODO parallelize + error-handling (might want to retry here)
                msg = SchemaRemoteSigner.ProposerPreferencesSignableMessage(
                    proposer_preferences=SchemaRemoteSigner.ProposerPreferences(
                        # Lodestar is throwing "PROPOSER_PREFERENCES_ERROR_UNKNOWN_DEPENDENT_ROOT"
                        # ... dependent roots changed a bit in Gloas so may have sth to do with that
                        dependent_root=self.proposer_duties_dependent_roots[epoch],
                        proposal_slot=duty.slot,
                        validator_index=duty.validator_index,
                        fee_recipient=default_fee_recipient
                        if not self.keymanager.enabled
                        else self.keymanager.pubkey_to_fee_recipient_override.get(
                            duty.pubkey, default_fee_recipient
                        ),
                        target_gas_limit=default_target_gas_limit
                        if not self.keymanager.enabled
                        else self.keymanager.pubkey_to_gas_limit_override.get(
                            duty.pubkey, default_target_gas_limit
                        ),
                    ),
                    fork_info=_fork_info,
                )
                signed_preferences.append(
                    await self.signature_provider.sign(
                        message=msg,
                        identifier=duty.pubkey,
                    )
                )

            if len(signed_preferences) == 0:
                continue

            # TODO unhardcode
            _fork_version = SchemaShared.ForkVersion.GLOAS

            # TODO submit to builders directly instead of via beacon node
            # await self.bid_selector.multi_builder.submit_proposer_preferences(...)
            await self.multi_beacon_node.submit_proposer_preferences(
                signed_proposer_preferences=[
                    (msg.proposer_preferences, sig)
                    for (msg, sig, _) in signed_preferences
                ],
                fork_version=_fork_version,
            )

            self.logger.info(
                f"Submitted proposer preferences for epoch {epoch}, count: {len(signed_preferences)}"
            )

    async def _fetch_randao_reveal(self, slot: int, pubkey: str) -> None:
        self.logger.debug(f"Fetching RANDAO reveal for slot {slot}")

        epoch = slot // self.beacon_chain.SLOTS_PER_EPOCH

        _, randao_reveal, _ = await self.signature_provider.sign(
            message=SchemaRemoteSigner.RandaoRevealSignableMessage(
                fork_info=self.beacon_chain.get_fork_info(slot=slot),
                randao_reveal=SchemaRemoteSigner.RandaoReveal(
                    epoch=str(epoch),
                ),
            ),
            identifier=pubkey,
        )
        self.randao_reveal_cache[(slot, pubkey)] = randao_reveal

    async def _get_randao_reveal(
        self,
        slot: int,
        pubkey: str,
    ) -> str:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}._get_randao_reveal",
        ):
            # Try to get it from the cache - it should be pre-populated
            # in the slot before a proposal is due
            cache_key = (slot, pubkey)
            with contextlib.suppress(KeyError):
                return self.randao_reveal_cache.pop(cache_key)

            # We failed to retrieve the value from the cache, fall back to
            # fetching it on-demand
            self.logger.warning(
                f"Failed to get RANDAO reveal from cache. Cache key: {cache_key}"
            )
            try:
                await self._fetch_randao_reveal(slot=slot, pubkey=pubkey)
            except Exception as e:
                self.logger.exception(
                    f"Failed to get RANDAO reveal: {e!r}",
                )
                raise HandledRuntimeError(
                    errors_counter=self.metrics.errors_c,
                    error_type=ErrorType.BLOCK_PRODUCE,
                ) from None
            else:
                return self.randao_reveal_cache.pop(cache_key)

    async def _produce_block(
        self,
        slot: int,
        duty: SchemaBeaconAPI.ProposerDuty,
        randao_reveal: str,
        signed_payload_bid: SchemaShared.SignedExecutionPayloadBid | None,
    ) -> tuple[BeaconBlock, SchemaRemoteSigner.BeaconBlockHeader, BeaconNode]:
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
                    beacon_node,
                ) = await self.multi_beacon_node.produce_block(
                    slot=slot,
                    graffiti=graffiti,
                    builder_boost_factor=self.cli_args.builder_boost_factor,
                    randao_reveal=randao_reveal,
                    signed_payload_bid=signed_payload_bid,
                    fork_version=self.beacon_chain.current_fork_version,
                    soft_timeout=self._block_production_soft_timeout,
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
                block_header = SchemaRemoteSigner.BeaconBlockHeader(
                    **block_contents_or_blinded_block.header_dict()
                )
                return block_contents_or_blinded_block, block_header, beacon_node

    async def _sign_block(
        self,
        slot: int,
        duty: SchemaBeaconAPI.ProposerDuty,
        block_header: SchemaRemoteSigner.BeaconBlockHeader,
        block_version: str,
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
        fork_version: SchemaShared.ForkVersion,
        signature: str,
        block_contents_or_blinded_block: BeaconBlock,
    ) -> BlockPublishResult:
        self.logger.info(f"Publishing block for slot {slot}")
        self.metrics.duty_submission_time_h.labels(
            duty=ValidatorDuty.BLOCK_PROPOSAL.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=slot))

        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}._publish_block",
        ):
            try:
                with block_contents_or_blinded_block.sign(
                    signature=signature
                ) as signed_object:
                    if self.cli_args.force_json_wire_format:
                        encoded = signed_object.to_json()
                        content_type = ContentType.JSON
                    else:
                        encoded = signed_object.to_ssz()
                        content_type = ContentType.OCTET_STREAM

                if (
                    block_contents_or_blinded_block.object_kind
                    is not ObjectKind.BLINDED_BEACON_BLOCK
                ):
                    await self.multi_beacon_node.publish_block_v2(
                        fork_version=fork_version,
                        signed_block_contents=encoded,
                        content_type=content_type,
                    )
                    # TODO in Gloas, we should also submit the block to the builder if
                    #  we used one
                else:
                    await self.multi_beacon_node.publish_blinded_block_v2(
                        fork_version=fork_version,
                        signed_blinded_beacon_block=encoded,
                        content_type=content_type,
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
                block_root = block_contents_or_blinded_block.block_hash_tree_root()
                self.logger.info(
                    f"Published block for slot {slot}, root {block_root}",
                )
                self.metrics.vc_published_blocks_c.inc()
                envelope_required = False
                if (
                    fork_version is SchemaShared.ForkVersion.GLOAS
                    and block_contents_or_blinded_block.body.signed_execution_payload_bid.message.builder_index
                    == BUILDER_INDEX_SELF_BUILD
                ):
                    envelope_required = True
                return BlockPublishResult(
                    block_root=block_root, envelope_required=envelope_required
                )

    async def _sign_execution_payload_envelope(
        self,
        slot: int,
        duty: SchemaBeaconAPI.ProposerDuty,
        execution_payload_envelope: ExecutionPayloadEnvelopeGloas,
    ) -> SignedExecutionPayloadEnvelopeGloas:
        # TODO based on tracing data this signing takes a pretty long time (>100ms)
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}._sign_execution_payload_envelope",
        ):
            try:
                _, signature, _ = await self.signature_provider.sign(
                    message=SchemaRemoteSigner.ExecutionPayloadEnvelopeSignableMessage(
                        fork_info=self.beacon_chain.get_fork_info(slot=slot),
                        execution_payload_envelope=(
                            SchemaRemoteSigner.ExecutionPayloadEnvelope(
                                **execution_payload_envelope.to_obj()
                            )
                        ),
                    ),
                    identifier=duty.pubkey,
                )
            except Exception as e:
                self.logger.exception(
                    f"Failed to get signature for execution payload envelope: {e!r}",
                )
                raise HandledRuntimeError(
                    errors_counter=self.metrics.errors_c, error_type=ErrorType.SIGNATURE
                ) from None
            return execution_payload_envelope.sign(signature)

    async def _publish_payload_envelope(
        self,
        slot: int,
        duty: SchemaBeaconAPI.ProposerDuty,
        beacon_block_root: str,
        beacon_node: BeaconNode,
    ) -> None:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}._publish_payload_envelope",
        ):
            # step 1 - get envelope by slot + beacon block root
            #  (if we add the include_payload query param we would not need to query for
            #  this payload separately)
            # step 2 sign envelope
            # step 3 publish signed envelope
            self.logger.info("Publishing payload envelope")
            # Only the beacon node that we got the BeaconBlock
            # from has its associated execution payload envelope.
            # (Unless running in stateless mode which Vero doesn't
            # support right now)
            (
                fork_version,
                execution_payload_envelope,
            ) = await beacon_node.get_execution_payload_envelope(
                slot=slot,
                beacon_block_root=beacon_block_root,
            )

            signed_execution_payload_envelope = (
                await self._sign_execution_payload_envelope(
                    slot=slot,
                    duty=duty,
                    execution_payload_envelope=execution_payload_envelope,
                )
            )
            with signed_execution_payload_envelope:
                if self.cli_args.force_json_wire_format:
                    encoded = signed_execution_payload_envelope.to_json()
                    content_type = ContentType.JSON
                else:
                    encoded = signed_execution_payload_envelope.to_ssz()
                    content_type = ContentType.OCTET_STREAM

            # Publish using the beacon node that produced the envelope,
            # because it also has cached blob data for that envelope.
            # We could also retrieve the full envelope-contents
            # for a stateless flow - not implemented right now.
            await beacon_node.publish_execution_payload_envelope(
                signed_execution_payload_envelope=encoded,
                fork_version=fork_version,
                content_type=content_type,
            )
            self.logger.info("Published payload envelope")

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
            randao_reveal = await self._get_randao_reveal(slot=slot, pubkey=duty.pubkey)

            selected_bid = None
            if self.beacon_chain.current_fork_version in (
                SchemaShared.ForkVersion.GLOAS,
            ):
                selected_bid = await self.bid_selector.get_bid(
                    slot=slot, proposer_duty=duty
                )

            (
                block_contents_or_blinded_block,
                block_header,
                beacon_node,
            ) = await self._produce_block(
                slot=slot,
                duty=duty,
                randao_reveal=randao_reveal,
                signed_payload_bid=selected_bid,
            )
            try:
                fork_version = SchemaShared.ForkVersion[
                    block_contents_or_blinded_block.fork.name
                ]
                signature = await self._sign_block(
                    slot=slot,
                    duty=duty,
                    block_header=block_header,
                    block_version=fork_version.value.upper(),
                )

                block_publish_result = await self._publish_block(
                    slot=slot,
                    fork_version=fork_version,
                    signature=signature,
                    block_contents_or_blinded_block=block_contents_or_blinded_block,
                )

                # TODO test - we MUST publish the envelope in this case!
                # TODO we probably want to do this more async - we don't want to be
                #  blocked too long by the above block-publish call that IIRC
                #  has no timeout
                if block_publish_result.envelope_required:
                    self.task_manager.create_task(
                        self._publish_payload_envelope(
                            slot=slot,
                            duty=duty,
                            beacon_block_root=block_publish_result.block_root,
                            beacon_node=beacon_node,
                        )
                    )

            finally:
                block_contents_or_blinded_block.close()

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
            # TODO take into account we also need to publish the envelope
            #  when self-building
            self._last_slot_duty_completed_for = slot
