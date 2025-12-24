import asyncio
import contextlib
import datetime
from collections import defaultdict
from types import TracebackType
from typing import Self, Unpack
from uuid import uuid4

from apscheduler.jobstores.base import JobLookupError

from observability import ErrorType, HandledRuntimeError
from schemas import SchemaBeaconAPI, SchemaRemoteSigner, SchemaValidator
from services.validator_duty_service import (
    ValidatorDuty,
    ValidatorDutyService,
    ValidatorDutyServiceOptions,
)
from spec.common import bytes_to_uint64, hash_function
from spec.constants import (
    SYNC_COMMITTEE_SUBNET_COUNT,
    TARGET_AGGREGATORS_PER_SYNC_SUBCOMMITTEE,
)
from spec.sync_committee import SpecSyncCommittee

_PRODUCE_JOB_ID = "SyncCommitteeService.produce_sync_message-slot-{duty_slot}"


class SyncCommitteeService(ValidatorDutyService):
    def __init__(self, **kwargs: Unpack[ValidatorDutyServiceOptions]) -> None:
        super().__init__(**kwargs)

        self._sync_message_due_s = (
            int(self.spec.SLOT_DURATION_MS * self.spec.SYNC_MESSAGE_DUE_BPS)
            / 10_000_000
        )
        self._contribution_due_s = (
            int(self.spec.SLOT_DURATION_MS * self.spec.CONTRIBUTION_DUE_BPS)
            / 10_000_000
        )

        # Sync duties by sync committee period
        self.sync_duties: defaultdict[int, list[SchemaBeaconAPI.SyncDuty]] = (
            defaultdict(list)
        )

    async def __aenter__(self) -> Self:
        try:
            duties = self.duty_cache.load_sync_duties()
            self.sync_duties = defaultdict(list, duties)
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
            self.duty_cache.cache_sync_duties(duties=self.sync_duties)
        except Exception as e:
            self.logger.warning(f"Failed to cache duties: {e}")

    def has_duty_for_slot(self, slot: int) -> bool:
        epoch = slot // self.beacon_chain.SLOTS_PER_EPOCH

        sync_period = self.beacon_chain.compute_sync_period_for_epoch(epoch)

        return len(self.sync_duties[sync_period]) > 0

    async def on_new_slot(self, slot: int, is_new_epoch: bool) -> None:
        # Schedule sync message job at the deadline in case
        # it is not triggered earlier by a new HeadEvent,
        # aiming to produce it 1/3 into the slot at the latest.
        _produce_deadline = datetime.datetime.fromtimestamp(
            timestamp=self.beacon_chain.get_timestamp_for_slot(slot)
            + self._sync_message_due_s,
            tz=datetime.UTC,
        )

        self.scheduler.add_job(
            func=self.produce_sync_message,
            trigger="date",
            next_run_time=_produce_deadline,
            kwargs=dict(duty_slot=slot),
            id=_PRODUCE_JOB_ID.format(duty_slot=slot),
            replace_existing=True,
        )

        # At the start of an epoch, update duties
        if is_new_epoch:
            self.task_manager.create_task(super().update_duties())

    async def handle_head_event(self, event: SchemaBeaconAPI.HeadEvent, _: str) -> None:
        await self.produce_sync_message(
            duty_slot=int(event.slot),
            head_event=event,
        )

    async def _get_head_block_root(self) -> str:
        try:
            return await self.multi_beacon_node.get_block_root(
                block_id="head",
            )
        except Exception as e:
            self.logger.exception(
                f"Failed to get beacon block root: {e!r}",
            )
            raise HandledRuntimeError(
                errors_counter=self.metrics.errors_c,
                error_type=ErrorType.SYNC_COMMITTEE_MESSAGE_PRODUCE,
            ) from None

    async def _get_signed_sync_messages(
        self,
        duty_slot: int,
        sync_committee_members: set[SchemaValidator.ValidatorIndexPubkey],
        beacon_block_root: str,
    ) -> list[SchemaBeaconAPI.SyncCommitteeSignature]:
        _fork_info = self.beacon_chain.get_fork_info(slot=duty_slot)
        coroutines = [
            self.signature_provider.sign(
                message=SchemaRemoteSigner.SyncCommitteeMessageSignableMessage(
                    fork_info=_fork_info,
                    sync_committee_message=SchemaRemoteSigner.SyncCommitteeMessage(
                        beacon_block_root=beacon_block_root,
                        slot=str(duty_slot),
                    ),
                ),
                identifier=validator.pubkey,
            )
            for validator in sync_committee_members
        ]

        signed_messages: list[SchemaBeaconAPI.SyncCommitteeSignature] = []
        for coro in asyncio.as_completed(coroutines):
            try:
                msg, sig, pubkey = await coro
            except Exception as e:
                self.metrics.errors_c.labels(error_type=ErrorType.SIGNATURE.value).inc()
                self.logger.exception(
                    f"Failed to get signature for sync committee message for slot {duty_slot}: {e!r}",
                )
                continue

            signed_messages.append(
                SchemaBeaconAPI.SyncCommitteeSignature(
                    beacon_block_root=msg.sync_committee_message.beacon_block_root,
                    slot=str(msg.sync_committee_message.slot),
                    validator_index=next(
                        str(v.index)
                        for v in sync_committee_members
                        if v.pubkey == pubkey
                    ),
                    signature=sig,
                ),
            )

        return signed_messages

    async def _publish_sync_messages(
        self,
        duty_slot: int,
        signed_sync_messages: list[SchemaBeaconAPI.SyncCommitteeSignature],
    ) -> None:
        self.logger.debug(
            f"Publishing sync committee messages for slot {duty_slot}, count: {len(signed_sync_messages)}",
        )

        self.metrics.duty_submission_time_h.labels(
            duty=ValidatorDuty.SYNC_COMMITTEE_MESSAGE.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=duty_slot))
        try:
            await self.multi_beacon_node.publish_sync_committee_messages(
                messages=signed_sync_messages,
            )
        except Exception as e:
            self.logger.exception(
                f"Failed to publish sync committee messages for slot {duty_slot}: {e!r}",
            )
            raise HandledRuntimeError(
                errors_counter=self.metrics.errors_c,
                error_type=ErrorType.SYNC_COMMITTEE_MESSAGE_PUBLISH,
            ) from None
        else:
            self.logger.info(
                f"Published sync committee messages for slot {duty_slot}, count: {len(signed_sync_messages)}",
            )
            self.metrics.vc_published_sync_committee_messages_c.inc(
                amount=len(signed_sync_messages),
            )

    async def _produce_sync_message(
        self,
        duty_slot: int,
        sync_period: int,
        head_event: SchemaBeaconAPI.HeadEvent | None,
        sync_committee_members: set[SchemaValidator.ValidatorIndexPubkey],
    ) -> None:
        self.logger.debug(
            f"Producing sync message for slot {duty_slot} for {len(sync_committee_members)} validators, from head: {head_event is not None}",
        )
        self._last_slot_duty_started_for = duty_slot
        self.metrics.duty_start_time_h.labels(
            duty=ValidatorDuty.SYNC_COMMITTEE_MESSAGE.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=duty_slot))

        beacon_block_root = (
            head_event.block if head_event else await self._get_head_block_root()
        )

        # Use the beacon_block_root later on for sync contribution duties
        self.task_manager.create_task(
            self.prepare_and_aggregate_sync_messages(
                duty_slot=duty_slot,
                beacon_block_root=beacon_block_root,
                sync_duties=self.sync_duties[sync_period],
            ),
        )

        # Sign the sync messages
        signed_sync_messages = await self._get_signed_sync_messages(
            duty_slot=duty_slot,
            sync_committee_members=sync_committee_members,
            beacon_block_root=beacon_block_root,
        )

        # Publish the messages
        await self._publish_sync_messages(
            duty_slot=duty_slot, signed_sync_messages=signed_sync_messages
        )

    async def produce_sync_message(
        self,
        duty_slot: int,
        head_event: SchemaBeaconAPI.HeadEvent | None = None,
    ) -> None:
        # Using < and not <= on purpose: if a head event comes in late,
        # we still want to produce a sync message for that block root too
        # since it is not slashable to publish 2 different sync messages
        # and it increases the chance of getting the sync message included
        # in the next block.
        if duty_slot < self._last_slot_duty_started_for:
            self.logger.debug(
                f"Not producing message during slot {duty_slot} - already started producing message during slot {self._last_slot_duty_started_for}"
            )
            return

        if duty_slot != self.beacon_chain.current_slot:
            raise RuntimeError(
                f"Invalid duty_slot for sync committee message: {duty_slot}. Current slot: {self.beacon_chain.current_slot}"
            )

        # See https://github.com/ethereum/consensus-specs/blob/dev/specs/altair/validator.md#sync-committee
        sync_period = self.beacon_chain.compute_sync_period_for_slot(duty_slot + 1)

        sync_committee_members = {
            SchemaValidator.ValidatorIndexPubkey(
                index=int(d.validator_index),
                pubkey=d.pubkey,
                status=SchemaBeaconAPI.ValidatorStatus.ACTIVE_ONGOING,
            )
            for d in self.sync_duties[sync_period]
        }

        if head_event is not None:
            # Cancel the scheduled job that would call this function
            # at 1/3 of the slot time if it has not yet been called
            with contextlib.suppress(JobLookupError):
                self.scheduler.remove_job(
                    job_id=_PRODUCE_JOB_ID.format(duty_slot=duty_slot),
                )

        if len(sync_committee_members) == 0:
            self.logger.debug(f"No remaining sync duties for slot {duty_slot}")
            return

        try:
            await self._produce_sync_message(
                duty_slot=duty_slot,
                head_event=head_event,
                sync_period=sync_period,
                sync_committee_members=sync_committee_members,
            )
        finally:
            self._last_slot_duty_completed_for = duty_slot

    async def prepare_and_aggregate_sync_messages(
        self,
        duty_slot: int,
        beacon_block_root: str,
        sync_duties: list[SchemaBeaconAPI.SyncDuty],
    ) -> None:
        # Prepare data for contribution and proof
        _fork_info = self.beacon_chain.get_fork_info(slot=duty_slot)
        selection_proofs_coroutines = []
        for duty in sync_duties:
            subcommittee_indexes = self._compute_subnets_for_sync_committee(
                [int(i) for i in duty.validator_sync_committee_indices],
            )
            selection_proofs_coroutines.extend(
                [
                    self.signature_provider.sign(
                        SchemaRemoteSigner.SyncCommitteeSelectionProofSignableMessage(
                            fork_info=_fork_info,
                            sync_aggregator_selection_data=SchemaRemoteSigner.SyncAggregatorSelectionData(
                                slot=str(duty_slot),
                                subcommittee_index=str(subcommittee_index),
                            ),
                        ),
                        identifier=duty.pubkey,
                    )
                    for subcommittee_index in subcommittee_indexes
                ]
            )

        try:
            selection_proofs = await asyncio.gather(*selection_proofs_coroutines)
        except Exception as e:
            self.logger.exception(
                f"Failed to get signatures for sync selection proofs for slot {duty_slot}: {e!r}",
            )
            raise HandledRuntimeError(
                errors_counter=self.metrics.errors_c, error_type=ErrorType.SIGNATURE
            ) from None

        duties_with_proofs = []
        for duty in sync_duties:
            duty_sync_committee_selection_proofs = []
            for sel_proof_msg, sig, identifier in selection_proofs:
                if identifier != duty.pubkey:
                    continue

                selection_proof = bytes.fromhex(sig[2:])

                duty_sync_committee_selection_proofs.append(
                    SchemaBeaconAPI.SyncDutySubCommitteeSelectionProof(
                        slot=int(sel_proof_msg.sync_aggregator_selection_data.slot),
                        subcommittee_index=int(
                            sel_proof_msg.sync_aggregator_selection_data.subcommittee_index
                        ),
                        is_aggregator=self._is_aggregator(selection_proof),
                        selection_proof=selection_proof,
                    ),
                )

            duties_with_proofs.append(
                SchemaBeaconAPI.SyncDutyWithSelectionProofs(
                    pubkey=duty.pubkey,
                    validator_index=duty.validator_index,
                    validator_sync_committee_indices=duty.validator_sync_committee_indices,
                    selection_proofs=duty_sync_committee_selection_proofs,
                ),
            )

        # Sign and submit aggregated sync committee contributions at 2/3 of the slot
        aggregation_run_time = datetime.datetime.fromtimestamp(
            timestamp=self.beacon_chain.get_timestamp_for_slot(duty_slot)
            + self._contribution_due_s,
            tz=datetime.UTC,
        )
        self.scheduler.add_job(
            self.aggregate_sync_messages,
            kwargs=dict(
                duty_slot=duty_slot,
                beacon_block_root=beacon_block_root,
                duties_with_proofs=duties_with_proofs,
            ),
            next_run_time=aggregation_run_time,
            id=f"{self.__class__.__name__}.aggregate_sync_messages-{duty_slot}-{uuid4()}",
        )

    async def _sign_and_publish_contributions(
        self,
        duty_slot: int,
        messages: list[
            SchemaRemoteSigner.SyncCommitteeContributionAndProofSignableMessage
        ],
        identifiers: list[str],
    ) -> None:
        signed_contribution_and_proofs = []
        for msg, sig, _identifier in await self.signature_provider.sign_in_batches(
            messages=messages,
            identifiers=identifiers,
        ):
            signed_contribution_and_proofs.append((msg.contribution_and_proof, sig))

        self.metrics.duty_submission_time_h.labels(
            duty=ValidatorDuty.SYNC_COMMITTEE_CONTRIBUTION.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=duty_slot))

        try:
            await self.multi_beacon_node.publish_sync_committee_contribution_and_proofs(
                signed_contribution_and_proofs=signed_contribution_and_proofs,
            )
            self.metrics.vc_published_sync_committee_contributions_c.inc(
                amount=len(signed_contribution_and_proofs),
            )
        except Exception as e:
            self.logger.exception(
                f"Failed to publish sync committee contribution and proofs for slot {duty_slot}: {e!r}",
            )
            raise HandledRuntimeError(
                errors_counter=self.metrics.errors_c,
                error_type=ErrorType.SYNC_COMMITTEE_CONTRIBUTION_PUBLISH,
            ) from None

    async def aggregate_sync_messages(
        self,
        duty_slot: int,
        beacon_block_root: str,
        duties_with_proofs: list[SchemaBeaconAPI.SyncDutyWithSelectionProofs],
    ) -> None:
        slot_sync_aggregate_duties = [
            d
            for d in duties_with_proofs
            if any(sp.is_aggregator for sp in d.selection_proofs)
        ]
        self.logger.debug(
            f"Aggregating sync committee messages for slot {duty_slot}, {len(slot_sync_aggregate_duties)} duties",
        )
        self.metrics.duty_start_time_h.labels(
            duty=ValidatorDuty.SYNC_COMMITTEE_CONTRIBUTION.value,
        ).observe(self.beacon_chain.time_since_slot_start(slot=duty_slot))

        if len(slot_sync_aggregate_duties) == 0:
            # No aggregators for this slot -> no need to go further
            return

        # Get aggregate contribution(s) from beacon node
        unique_subcommittee_indices = {
            sp.subcommittee_index
            for duty in slot_sync_aggregate_duties
            for sp in duty.selection_proofs
            if sp.is_aggregator
        }

        contribution_count = 0
        self.logger.debug(
            f"Starting sync committee contribution and proof sign-and-publish tasks for slot {duty_slot}",
        )

        _fork_info = self.beacon_chain.get_fork_info(slot=duty_slot)
        _sign_and_publish_tasks = []
        async for (
            contribution
        ) in self.multi_beacon_node.get_sync_committee_contributions(
            slot=duty_slot,
            subcommittee_indices=unique_subcommittee_indices,
            beacon_block_root=beacon_block_root,
        ):
            messages = []
            identifiers = []
            for duty in slot_sync_aggregate_duties:
                for duty_sp in duty.selection_proofs:
                    if (
                        duty_sp.subcommittee_index == contribution.subcommittee_index
                        and duty_sp.is_aggregator
                    ):
                        contribution_count += 1
                        messages.append(
                            SchemaRemoteSigner.SyncCommitteeContributionAndProofSignableMessage(
                                fork_info=_fork_info,
                                contribution_and_proof=SpecSyncCommittee.ContributionAndProof(
                                    aggregator_index=int(duty.validator_index),
                                    contribution=contribution,
                                    selection_proof=duty_sp.selection_proof,
                                ).to_obj(),
                            )
                        )
                        identifiers.append(duty.pubkey)

            _sign_and_publish_tasks.append(
                asyncio.create_task(
                    self._sign_and_publish_contributions(
                        duty_slot=duty_slot,
                        messages=messages,
                        identifiers=identifiers,
                    )
                )
            )

        await asyncio.gather(*_sign_and_publish_tasks)
        self.logger.info(
            f"Published sync committee contribution and proofs for slot {duty_slot}, count: {contribution_count}"
        )

    def _compute_subnets_for_sync_committee(
        self,
        indexes_in_committee: list[int],
    ) -> set[int]:
        subnets = set()

        for idx in indexes_in_committee:
            subnets.add(
                idx
                // int(
                    self.beacon_chain.SYNC_COMMITTEE_SIZE // SYNC_COMMITTEE_SUBNET_COUNT
                ),
            )

        return subnets

    def _is_aggregator(self, selection_proof: bytes) -> bool:
        modulo = max(
            1,
            self.beacon_chain.SYNC_COMMITTEE_SIZE
            // SYNC_COMMITTEE_SUBNET_COUNT
            // TARGET_AGGREGATORS_PER_SYNC_SUBCOMMITTEE,
        )
        return bytes_to_uint64(hash_function(selection_proof)[0:8]) % modulo == 0  # type: ignore[no-any-return]

    def _prune_duties(self) -> None:
        current_epoch = self.beacon_chain.current_epoch
        current_sync_period = self.beacon_chain.compute_sync_period_for_epoch(
            current_epoch,
        )
        for sync_period in list(self.sync_duties.keys()):
            if sync_period < current_sync_period:
                del self.sync_duties[sync_period]

    async def _update_duties(self) -> None:
        # We check for duties for exited validators here too since
        # it is possible for an exited validator to be scheduled for
        # sync commitee duties (when scheduled shortly before the
        # validator exits).
        # Even a validator in `withdrawal_done` status
        # can still be scheduled for sync committee duties!
        # See https://ethresear.ch/t/sync-committees-exited-validators-participating-in-sync-committee/15634
        _validator_indices = (
            self.validator_status_tracker_service.active_or_pending_indices
            + self.validator_status_tracker_service.exited_or_withdrawal_indices
        )

        if len(_validator_indices) == 0:
            self.logger.warning(
                "Not updating sync committee duties - no active, pending, or exited validators",
            )
            return
        self.logger.debug(
            f"Updating sync commitee duties for {len(_validator_indices)} validators"
        )

        current_epoch = self.beacon_chain.current_epoch
        # TODO we current update sync duties way too often.
        #  We only need to update them once in a while
        #  (SUBSCRIPTIONS_LOOKAHEAD_EPOCHS)
        #  (sync duties are known far in advance and we really don't need to query
        #  them every epoch)
        #  When fixing this, be careful with the one-off bug, probably
        #  deserves a test or two to make sure we're handling it right!
        #  ( https://github.com/ethereum/consensus-specs/blob/dev/specs/altair/validator.md#sync-committee )

        for epoch in (current_epoch,):
            sync_period = self.beacon_chain.compute_sync_period_for_epoch(epoch)
            self.logger.debug(
                f"Updating sync duties for epoch {epoch} -> sync period {sync_period}",
            )

            response = await self.multi_beacon_node.get_sync_duties(
                epoch=epoch,
                indices=_validator_indices,
            )
            fetched_duties = response.data

            if len(fetched_duties) == 0:
                continue

            self.sync_duties[sync_period] = fetched_duties

            # Prepare sync committee subnet subscriptions for aggregation duties
            until_epoch = (
                sync_period + 1
            ) * self.beacon_chain.EPOCHS_PER_SYNC_COMMITTEE_PERIOD
            sync_committee_subscriptions_data = [
                SchemaBeaconAPI.SubscribeToSyncCommitteeSubnetRequestBody(
                    validator_index=duty.validator_index,
                    sync_committee_indices=duty.validator_sync_committee_indices,
                    until_epoch=str(until_epoch),
                )
                for duty in self.sync_duties[sync_period]
            ]
            self.task_manager.create_task(
                self.multi_beacon_node.prepare_sync_committee_subscriptions(
                    data=sync_committee_subscriptions_data,
                )
            )

            self.logger.debug(
                f"Updated duties for epoch {epoch} -> sync period {sync_period} -> {len(self.sync_duties[sync_period])}",
            )

        self._prune_duties()
