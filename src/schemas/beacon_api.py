"""API response models for the Beacon Node API.

Useful links:

https://github.com/ethereum/beacon-APIs
https://ethereum.github.io/beacon-APIs/

https://docs.nodereal.io/reference/eventstream
"""

from collections.abc import Hashable
from enum import Enum
from typing import Any, Self

import msgspec

from schemas.shared import (
    ForkVersion,
    SignedBuilderRequestAuth,
    SignedExecutionPayloadBid,
)


class ExecutionOptimisticResponse(msgspec.Struct):
    execution_optimistic: bool


class ValidatorStatus(Enum):
    PENDING_INITIALIZED = "pending_initialized"
    PENDING_QUEUED = "pending_queued"
    ACTIVE_ONGOING = "active_ongoing"
    ACTIVE_EXITING = "active_exiting"
    ACTIVE_SLASHED = "active_slashed"
    EXITED_UNSLASHED = "exited_unslashed"
    EXITED_SLASHED = "exited_slashed"
    WITHDRAWAL_POSSIBLE = "withdrawal_possible"
    WITHDRAWAL_DONE = "withdrawal_done"


class Validator(msgspec.Struct):
    pubkey: str
    withdrawal_credentials: str
    effective_balance: str
    slashed: bool
    activation_eligibility_epoch: str
    activation_epoch: str
    exit_epoch: str
    withdrawable_epoch: str


class ValidatorInfo(msgspec.Struct):
    index: str
    balance: str
    status: ValidatorStatus
    validator: Validator


class GetStateValidatorsResponse(ExecutionOptimisticResponse):
    finalized: bool
    data: list[ValidatorInfo]


class BlockRoot(msgspec.Struct):
    root: str


class GetBlockRootResponse(ExecutionOptimisticResponse):
    finalized: bool
    data: BlockRoot


class SubscribeToBeaconCommitteeSubnetRequestBody(msgspec.Struct):
    validator_index: str
    committee_index: str
    committees_at_slot: str
    slot: str
    is_aggregator: bool


class SubscribeToSyncCommitteeSubnetRequestBody(msgspec.Struct):
    validator_index: str
    sync_committee_indices: list[str]
    until_epoch: str


class GetAggregatedAttestationV2Response(msgspec.Struct):
    version: ForkVersion
    data: msgspec.Raw


class RawDataResponse(msgspec.Struct):
    data: msgspec.Raw


# Duty endpoints responses
class ProposerDuty(msgspec.Struct, frozen=True):
    pubkey: str
    validator_index: str
    slot: str


class GetProposerDutiesResponse(ExecutionOptimisticResponse):
    dependent_root: str
    data: list[ProposerDuty]


class AttesterDuty(msgspec.Struct, frozen=True):
    pubkey: str
    validator_index: str
    committee_index: str
    committee_length: str
    committees_at_slot: str
    validator_committee_index: str
    slot: str

    def to_dict(self) -> dict[str, str]:
        return {f: getattr(self, f) for f in self.__struct_fields__}


class AttesterDutyWithSelectionProof(AttesterDuty, frozen=True):
    is_aggregator: bool
    selection_proof: bytes

    @classmethod
    def from_duty(
        cls, duty: AttesterDuty, is_aggregator: bool, selection_proof: bytes
    ) -> Self:
        return cls(
            pubkey=duty.pubkey,
            validator_index=duty.validator_index,
            committee_index=duty.committee_index,
            committee_length=duty.committee_length,
            committees_at_slot=duty.committees_at_slot,
            validator_committee_index=duty.validator_committee_index,
            slot=duty.slot,
            is_aggregator=is_aggregator,
            selection_proof=selection_proof,
        )


class GetAttesterDutiesResponse(ExecutionOptimisticResponse):
    dependent_root: str
    data: list[AttesterDuty]


class SyncDuty(msgspec.Struct):
    pubkey: str
    validator_index: str
    validator_sync_committee_indices: list[str]


class SyncDutySubCommitteeSelectionProof(msgspec.Struct):
    slot: int
    subcommittee_index: int
    is_aggregator: bool
    selection_proof: bytes


class SyncDutyWithSelectionProofs(SyncDuty):
    selection_proofs: list[SyncDutySubCommitteeSelectionProof]


class GetSyncDutiesResponse(ExecutionOptimisticResponse):
    data: list[SyncDuty]


class PtcDuty(msgspec.Struct, frozen=True):
    pubkey: str
    validator_index: str
    slot: str


class GetPtcDutiesResponse(ExecutionOptimisticResponse):
    dependent_root: str
    data: list[PtcDuty]


# Block production
class ProduceBlockV3Response(msgspec.Struct):
    version: ForkVersion
    execution_payload_blinded: bool
    execution_payload_value: str
    consensus_block_value: str
    data: bytes


class BuilderEntry(msgspec.Struct):
    url: str
    auth: SignedBuilderRequestAuth
    builder_pubkeys: list[str]
    max_execution_payment: str
    min_bid: str
    builder_boost_factor: str


class BuilderConfig(msgspec.Struct):
    min_bid: str
    builder_boost_factor: str
    builders: list[BuilderEntry]


class ProduceBlockV4Response(msgspec.Struct):
    version: ForkVersion
    execution_payload_included: bool
    execution_payload_value: str
    consensus_block_value: str
    builder_url: str | None
    data: bytes


class GetExecutionPayloadEnvelopeResponse(msgspec.Struct):
    version: ForkVersion
    data: bytes


# Liveness endpoint
class ValidatorLiveness(msgspec.Struct):
    index: str
    is_live: bool


class PostLivenessResponseBody(msgspec.Struct):
    data: list[ValidatorLiveness]


# Events
class BeaconNodeEvent(msgspec.Struct):
    @property
    def dedup_key(self) -> Hashable:
        raise NotImplementedError


class HeadV2EventData(msgspec.Struct):
    slot: str
    block: str
    state: str
    payload_status: str
    epoch_transition: bool
    current_epoch_dependent_root: str
    next_epoch_dependent_root: str
    execution_optimistic: bool


class HeadV2Event(BeaconNodeEvent):
    version: ForkVersion
    data: HeadV2EventData

    @property
    def dedup_key(self) -> Hashable:
        return "head_v2 " + self.data.block


class ExecutionPayloadAvailableEvent(BeaconNodeEvent):
    slot: str
    block_root: str

    @property
    def dedup_key(self) -> Hashable:
        # A head event's dedup key is also the block root,
        # so we need to differentiate by using an event-specific prefix
        return "epa " + self.block_root


class ChainReorgEvent(BeaconNodeEvent, ExecutionOptimisticResponse):
    slot: str
    depth: str
    old_head_block: str
    new_head_block: str

    @property
    def dedup_key(self) -> Hashable:
        return "reorg " + self.new_head_block


# Slashing events
class AttesterSlashingEventAttestation(msgspec.Struct):
    attesting_indices: list[str]


class AttesterSlashingEvent(BeaconNodeEvent):
    attestation_1: AttesterSlashingEventAttestation
    attestation_2: AttesterSlashingEventAttestation

    @property
    def dedup_key(self) -> Hashable:
        return "att_slash " + str(
            set(self.attestation_1.attesting_indices)
            & set(self.attestation_2.attesting_indices)
        )


class ProposerSlashingEventMessage(msgspec.Struct):
    proposer_index: str


class ProposerSlashingEventData(msgspec.Struct):
    message: ProposerSlashingEventMessage


class ProposerSlashingEvent(BeaconNodeEvent):
    signed_header_1: ProposerSlashingEventData
    signed_header_2: ProposerSlashingEventData

    @property
    def dedup_key(self) -> Hashable:
        return "prop_slash " + self.signed_header_1.message.proposer_index


class ExecutionPayloadBidEvent(BeaconNodeEvent):
    version: ForkVersion
    data: SignedExecutionPayloadBid

    @property
    def dedup_key(self) -> Hashable:
        return "bid " + self.data.message.block_hash + self.data.message.value


class PayloadAttributesData(msgspec.Struct):
    proposer_index: str
    proposal_slot: str
    parent_block_root: str
    parent_block_hash: str
    payload_attributes: dict[str, Any]


class PayloadAttributes(msgspec.Struct):
    version: ForkVersion
    data: PayloadAttributesData


class PayloadAttributesEvent(BeaconNodeEvent, PayloadAttributes):
    @property
    def dedup_key(self) -> Hashable:
        # TODO simplify if possible
        return (
            "payload_attrs "
            f"{self.data.proposal_slot}+{self.data.parent_block_root}+{self.data.proposer_index}"
        )


def is_optimistic(obj: ExecutionOptimisticResponse | BeaconNodeEvent) -> bool:
    if isinstance(obj, ExecutionOptimisticResponse):
        return obj.execution_optimistic
    if isinstance(obj, HeadV2Event):
        return obj.data.execution_optimistic

    return False
