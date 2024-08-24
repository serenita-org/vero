import asyncio
import datetime
import logging
from collections import defaultdict

from apscheduler.jobstores.base import JobLookupError

from schemas.validator import ValidatorStatus
from spec.common import bytes_to_uint64, hash_function
from spec.sync_committee import SyncCommitteeContributionClass
from prometheus_client import Counter

from schemas import SchemaBeaconAPI, SchemaRemoteSigner
from schemas import SchemaValidator
from services.validator_duty_service import ValidatorDutyService, ValidatorDuty
from observability import get_shared_metrics, ERROR_TYPE

logging.basicConfig()

_VC_PUBLISHED_SYNC_COMMITTEE_MESSAGES = Counter(
    "vc_published_sync_committee_messages",
    "Successfully published sync committee messages",
)
_VC_PUBLISHED_SYNC_COMMITTEE_MESSAGES.reset()

_VC_PUBLISHED_SYNC_COMMITTEE_CONTRIBUTIONS = Counter(
    "vc_published_sync_committee_contributions",
    "Successfully published sync committee contributions",
)
_VC_PUBLISHED_SYNC_COMMITTEE_MESSAGES.reset()
(_ERRORS_METRIC,) = get_shared_metrics()


_PRODUCE_JOB_ID = "produce_sync_message_if_not_yet_job_for_slot_{duty_slot}"


class SyncCommitteeService(ValidatorDutyService):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        # Sync duties by sync committee period
        self.sync_duties: defaultdict[int, list[SchemaBeaconAPI.SyncDuty]] = (
            defaultdict(list)
        )

    def start(self):
        self.scheduler.add_job(self.update_duties)

    async def handle_head_event(self, event: SchemaBeaconAPI.HeadEvent):
        if not isinstance(event, SchemaBeaconAPI.HeadEvent):
            raise NotImplementedError(f"Expected HeadEvent but got {type(event)}")
        await self.produce_sync_message_if_not_yet_produced(
            duty_slot=event.slot,
            head_event=event,
        )

    async def produce_sync_message_if_not_yet_produced(
        self,
        duty_slot: int,
        head_event: SchemaBeaconAPI.HeadEvent | None = None,
    ):
        if self.validator_status_tracker_service.slashing_detected:
            raise RuntimeError(
                "Slashing detected, not producing sync committee message"
            )

        if duty_slot <= self._last_slot_duty_performed_for:
            self.logger.warning(
                f"Not producing sync committee message during slot {duty_slot} (already started producing message during slot {self._last_slot_duty_performed_for})"
            )
            return
        self._last_slot_duty_performed_for = duty_slot

        # See https://github.com/ethereum/consensus-specs/blob/dev/specs/altair/validator.md#sync-committee
        sync_period = self.beacon_chain.compute_sync_period_for_slot(duty_slot + 1)

        sync_committee_members = set(
            SchemaValidator.ValidatorIndexPubkey(
                index=d.validator_index,
                pubkey=d.pubkey,
                status=ValidatorStatus.ACTIVE_ONGOING,
            )
            for d in self.sync_duties[sync_period]
        )

        if head_event is not None:
            # Cancel the scheduled job that would call this function
            # at 1/3 of the slot time if it has not yet been called
            try:
                self.scheduler.remove_job(
                    job_id=_PRODUCE_JOB_ID.format(duty_slot=duty_slot)
                )
            except JobLookupError:
                pass

        if len(sync_committee_members) == 0:
            self.logger.debug(f"No remaining sync duties for slot {duty_slot}")
            return

        self.logger.debug(
            f"Producing sync message for slot {duty_slot} for {len(sync_committee_members)} validators, from head: {head_event is not None}"
        )
        self._duty_start_time_metric.labels(
            duty=ValidatorDuty.SYNC_COMMITTEE_MESSAGE.value
        ).observe(self.beacon_chain.time_since_slot_start(slot=duty_slot))

        if head_event:
            beacon_block_root = head_event.block
        else:
            try:
                beacon_block_root = await self.multi_beacon_node.get_block_root(
                    block_id="head"
                )
            except Exception as e:
                self.logger.exception("Failed to get beacon block root")
                _ERRORS_METRIC.labels(
                    error_type=ERROR_TYPE.SYNC_COMMITTEE_MESSAGE_PRODUCE.value
                ).inc()
                raise e

        coroutines = []
        _fork_info = self.beacon_chain.get_fork_info(slot=duty_slot)
        for validator in sync_committee_members:
            coroutines.append(
                self.remote_signer.sign(
                    message=SchemaRemoteSigner.SyncCommitteeMessageSignableMessage(
                        fork_info=_fork_info,
                        sync_committee_message=SchemaRemoteSigner.SyncCommitteeMessage(
                            beacon_block_root=beacon_block_root, slot=duty_slot
                        ),
                    ),
                    identifier=validator.pubkey,
                )
            )

        sync_messages_to_publish = []
        for coro in asyncio.as_completed(coroutines):
            try:
                msg, sig, pubkey = await coro
            except Exception as e:
                _ERRORS_METRIC.labels(error_type=ERROR_TYPE.SIGNATURE.value).inc()
                self.logger.exception(
                    f"Failed to get signature for sync committee message for slot {duty_slot}: {e}"
                )
                continue

            sync_messages_to_publish.append(
                dict(
                    beacon_block_root=msg.sync_committee_message.beacon_block_root,
                    slot=str(msg.sync_committee_message.slot),
                    validator_index=next(
                        str(v.index)
                        for v in sync_committee_members
                        if v.pubkey == pubkey
                    ),
                    signature=sig,
                )
            )

        self._duty_submission_time_metric.labels(
            duty=ValidatorDuty.SYNC_COMMITTEE_MESSAGE.value
        ).observe(self.beacon_chain.time_since_slot_start(slot=duty_slot))
        try:
            await self.multi_beacon_node.publish_sync_committee_messages(
                messages=sync_messages_to_publish
            )
        except Exception:
            _ERRORS_METRIC.labels(
                error_type=ERROR_TYPE.SYNC_COMMITTEE_MESSAGE_PUBLISH.value
            ).inc()
            self.logger.error(
                f"Failed to publish sync committee messages for slot {duty_slot}"
            )
        else:
            self.logger.info(
                f"Published sync committee messages for slot {duty_slot}, count: {len(sync_committee_members)}"
            )
            _VC_PUBLISHED_SYNC_COMMITTEE_MESSAGES.inc(
                amount=len(sync_committee_members)
            )

        # Prepare data for contribution and proof
        _fork_info = self.beacon_chain.get_fork_info(slot=duty_slot)
        selection_proofs_coroutines = []
        for duty in self.sync_duties[sync_period]:
            subcommittee_indexes = self._compute_subnets_for_sync_committee(
                duty.validator_sync_committee_indices
            )
            for subcommittee_index in subcommittee_indexes:
                selection_proofs_coroutines.append(
                    self.remote_signer.sign(
                        SchemaRemoteSigner.SyncCommitteeSelectionProofSignableMessage(
                            fork_info=_fork_info,
                            sync_aggregator_selection_data=SchemaRemoteSigner.SyncAggregatorSelectionData(
                                slot=duty_slot, subcommittee_index=subcommittee_index
                            ),
                        ),
                        identifier=duty.pubkey,
                    )
                )

        try:
            selection_proofs = await asyncio.gather(*selection_proofs_coroutines)
        except Exception as e:
            _ERRORS_METRIC.labels(error_type=ERROR_TYPE.SIGNATURE.value).inc()
            self.logger.exception(
                f"Failed to get signatures for sync selection proofs for slot {duty_slot}: {e}"
            )
            return

        duties_with_proofs = []
        for duty in self.sync_duties[sync_period]:
            duty_sync_committee_selection_proofs = []
            for msg, sig, identifier in selection_proofs:
                if identifier != duty.pubkey:
                    continue

                selection_proof = bytes.fromhex(sig[2:])

                duty_sync_committee_selection_proofs.append(
                    SchemaBeaconAPI.SyncDutySubCommitteeSelectionProof(
                        slot=msg.sync_aggregator_selection_data.slot,
                        subcommittee_index=msg.sync_aggregator_selection_data.subcommittee_index,
                        is_aggregator=self._is_aggregator(selection_proof),
                        selection_proof=selection_proof,
                    )
                )

            duties_with_proofs.append(
                SchemaBeaconAPI.SyncDutyWithSelectionProofs(
                    **duty.model_dump(),
                    selection_proofs=duty_sync_committee_selection_proofs,
                )
            )

        # Sign and submit aggregated sync committee contributions at 2/3 of the slot
        aggregation_run_time = self.beacon_chain.get_datetime_for_slot(
            duty_slot
        ) + datetime.timedelta(
            seconds=2
            * int(self.beacon_chain.spec.SECONDS_PER_SLOT)
            / int(self.beacon_chain.spec.INTERVALS_PER_SLOT)
        )
        self.scheduler.add_job(
            self.aggregate_sync_messages,
            kwargs=dict(
                duties_with_proofs=duties_with_proofs,
                duty_slot=duty_slot,
                beacon_block_root=beacon_block_root,
            ),
            next_run_time=aggregation_run_time,
        )

    async def aggregate_sync_messages(
        self,
        duties_with_proofs: list[SchemaBeaconAPI.SyncDutyWithSelectionProofs],
        duty_slot: int,
        beacon_block_root: str,
    ) -> None:
        slot_sync_aggregate_duties = [
            d
            for d in duties_with_proofs
            if any(sp.is_aggregator for sp in d.selection_proofs)
        ]
        self.logger.debug(
            f"Aggregating sync committee messages for slot {duty_slot}, {len(slot_sync_aggregate_duties)} duties"
        )
        self._duty_start_time_metric.labels(
            duty=ValidatorDuty.SYNC_COMMITTEE_CONTRIBUTION.value
        ).observe(self.beacon_chain.time_since_slot_start(slot=duty_slot))

        if len(slot_sync_aggregate_duties) == 0:
            # No aggregators for this slot -> no need to go further
            return

        # Get aggregate contribution(s) from beacon node
        coroutines = []
        unique_subcommittee_indices = set(
            [
                sp.subcommittee_index
                for duty in slot_sync_aggregate_duties
                for sp in duty.selection_proofs
                if sp.is_aggregator
            ]
        )
        for subcommittee_index in unique_subcommittee_indices:
            coroutines.append(
                self.multi_beacon_node.get_sync_committee_contribution(
                    slot=duty_slot,
                    subcommittee_index=subcommittee_index,
                    beacon_block_root=beacon_block_root,
                )
            )

        try:
            contributions = await asyncio.gather(*coroutines)
        except Exception as e:
            _ERRORS_METRIC.labels(
                error_type=ERROR_TYPE.SYNC_COMMITTEE_CONTRIBUTION_PRODUCE.value
            ).inc()
            raise e

        self.logger.debug(f"Got contributions: {contributions}")

        coroutines = []
        for duty in slot_sync_aggregate_duties:
            slot_agg_selection_proofs = [
                sp for sp in duty.selection_proofs if sp.is_aggregator
            ]

            for sp in slot_agg_selection_proofs:
                contribution = next(
                    c
                    for c in contributions
                    if c.subcommittee_index == sp.subcommittee_index
                )

                _fork_info = self.beacon_chain.get_fork_info(slot=duty_slot)
                coroutines.append(
                    self.remote_signer.sign(
                        message=SchemaRemoteSigner.SyncCommitteeContributionAndProofSignableMessage(
                            fork_info=_fork_info,
                            contribution_and_proof=SyncCommitteeContributionClass.ContributionAndProof(
                                aggregator_index=duty.validator_index,
                                contribution=contribution,
                                selection_proof=sp.selection_proof,
                            ).to_obj(),
                        ),
                        identifier=duty.pubkey,
                    )
                )

        try:
            signed_contribution_and_proofs = [
                (msg.contribution_and_proof, sig)
                for msg, sig, identifier in await asyncio.gather(*coroutines)
            ]
        except Exception as e:
            _ERRORS_METRIC.labels(error_type=ERROR_TYPE.SIGNATURE.value).inc()
            self.logger.exception(
                f"Failed to get signatures for sync contributions and proofs for slot {duty_slot}: {e}"
            )
            raise e

        self._duty_submission_time_metric.labels(
            duty=ValidatorDuty.SYNC_COMMITTEE_CONTRIBUTION.value
        ).observe(self.beacon_chain.time_since_slot_start(slot=duty_slot))
        try:
            await self.multi_beacon_node.publish_sync_committee_contribution_and_proofs(
                signed_contribution_and_proofs=signed_contribution_and_proofs
            )
        except Exception:
            _ERRORS_METRIC.labels(
                error_type=ERROR_TYPE.SYNC_COMMITTEE_CONTRIBUTION_PUBLISH.value
            ).inc()
            self.logger.error(
                f"Failed to publish sync committee contribution and proofs for slot {duty_slot}"
            )
        else:
            self.logger.info(
                f"Published sync committee contribution and proofs for slot {duty_slot}, count: {len(signed_contribution_and_proofs)}"
            )
            _VC_PUBLISHED_SYNC_COMMITTEE_CONTRIBUTIONS.inc(
                len(signed_contribution_and_proofs)
            )

    def _compute_subnets_for_sync_committee(
        self, indexes_in_committee: list[int]
    ) -> set[int]:
        subnets = set()

        for idx in indexes_in_committee:
            subnets.add(
                idx
                // (
                    self.beacon_chain.spec.SYNC_COMMITTEE_SIZE
                    // self.beacon_chain.spec.SYNC_COMMITTEE_SUBNET_COUNT
                )
            )

        return subnets

    def _is_aggregator(self, selection_proof: bytes) -> bool:
        modulo = max(
            1,
            self.beacon_chain.spec.SYNC_COMMITTEE_SIZE
            // self.beacon_chain.spec.SYNC_COMMITTEE_SUBNET_COUNT
            // self.beacon_chain.spec.TARGET_AGGREGATORS_PER_SYNC_SUBCOMMITTEE,
        )
        return bytes_to_uint64(hash_function(selection_proof)[0:8]) % modulo == 0

    def _prune_duties(self) -> None:
        current_epoch = self.beacon_chain.current_epoch
        current_sync_period = self.beacon_chain.compute_sync_period_for_epoch(
            current_epoch
        )
        for sync_period in list(self.sync_duties.keys()):
            if sync_period < current_sync_period:
                del self.sync_duties[sync_period]

    async def _update_duties(self):
        if not self.validator_status_tracker_service.any_active_or_pending_validators:
            self.logger.warning(
                "Not updating sync committee duties - no active or pending validators"
            )
            return

        current_epoch = self.beacon_chain.current_epoch

        _validator_indices = [
            v.index
            for v in self.validator_status_tracker_service.active_validators
            + self.validator_status_tracker_service.pending_validators
        ]

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
                f"Updating sync duties for epoch {epoch} -> sync period {sync_period}"
            )

            response = await self.multi_beacon_node.get_sync_duties(
                epoch=epoch,
                indices=_validator_indices,
            )
            fetched_duties = response.data
            self.sync_duties[sync_period] = fetched_duties

            # Schedule sync committee message produce job
            # at the deadline in case it is not triggered earlier
            # by a new HeadEvent
            _latest_into_slot = int(self.beacon_chain.spec.SECONDS_PER_SLOT) / int(
                self.beacon_chain.spec.INTERVALS_PER_SLOT
            )
            current_slot = self.beacon_chain.current_slot

            for slot in range(
                self.beacon_chain.compute_start_slot_at_epoch(epoch),
                self.beacon_chain.compute_start_slot_at_epoch(epoch + 1),
            ):
                if slot < current_slot:
                    continue

                duty_run_time = self.beacon_chain.get_datetime_for_slot(
                    slot=slot
                ) + datetime.timedelta(seconds=_latest_into_slot)

                self.logger.debug(
                    f"Adding produce_sync_message_if_not_yet_produced job for slot {slot}"
                )
                self.scheduler.add_job(
                    self.produce_sync_message_if_not_yet_produced,
                    "date",
                    next_run_time=duty_run_time,
                    kwargs=dict(duty_slot=slot),
                    id=_PRODUCE_JOB_ID.format(duty_slot=slot),
                    replace_existing=True,
                )

            # Prepare sync committee subnet subscriptions for aggregation duties
            sync_committee_subscriptions_data = []
            until_epoch = (
                sync_period + 1
            ) * self.beacon_chain.spec.EPOCHS_PER_SYNC_COMMITTEE_PERIOD
            for duty in self.sync_duties[sync_period]:
                sync_committee_subscriptions_data.append(
                    dict(
                        validator_index=str(duty.validator_index),
                        sync_committee_indices=[
                            str(i) for i in duty.validator_sync_committee_indices
                        ],
                        until_epoch=str(until_epoch),
                    )
                )
            self.scheduler.add_job(
                self.multi_beacon_node.prepare_sync_committee_subscriptions,
                kwargs=dict(data=sync_committee_subscriptions_data),
            )

            self.logger.debug(
                f"Updated duties for epoch {epoch} -> sync period {sync_period} -> {len(self.sync_duties[sync_period])}"
            )

        self._prune_duties()
