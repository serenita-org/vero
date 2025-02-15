"""API response models for the Beacon Node API.

Useful links:

https://github.com/ethereum/beacon-APIs
https://ethereum.github.io/beacon-APIs/

https://docs.nodereal.io/reference/eventstream
"""

from enum import Enum

import msgspec


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


class ValidatorInfo(msgspec.Struct):
    index: str
    status: ValidatorStatus
    validator: Validator


class GetStateValidatorsResponse(ExecutionOptimisticResponse):
    data: list[ValidatorInfo]


class BlockRoot(msgspec.Struct):
    root: str


class GetBlockRootResponse(ExecutionOptimisticResponse):
    data: BlockRoot


class ForkVersion(Enum):
    DENEB = "deneb"
    ELECTRA = "electra"


class AttestationPhase0(msgspec.Struct):
    aggregation_bits: str
    data: dict  # type: ignore[type-arg]
    signature: str


class SingleAttestation(msgspec.Struct):
    committee_index: str
    attester_index: str
    data: dict  # type: ignore[type-arg]
    signature: str


class SubscribeToBeaconCommitteeSubnetRequestBody(msgspec.Struct):
    validator_index: str
    committee_index: str
    committees_at_slot: str
    slot: str
    is_aggregator: bool


class SyncCommitteeSignature(msgspec.Struct):
    slot: str
    beacon_block_root: str
    validator_index: str
    signature: str


class SubscribeToSyncCommitteeSubnetRequestBody(msgspec.Struct):
    validator_index: str
    sync_committee_indices: list[str]
    until_epoch: str


class GetAggregatedAttestationV2Response(msgspec.Struct):
    version: ForkVersion
    data: dict  # type: ignore[type-arg]


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


# Block production
class ProduceBlockV3Response(msgspec.Struct):
    version: ForkVersion
    execution_payload_blinded: bool
    execution_payload_value: str
    consensus_block_value: str
    data: dict | bytes  # type: ignore[type-arg]


# Events
class BeaconNodeEvent(msgspec.Struct):
    pass


class HeadEvent(BeaconNodeEvent, ExecutionOptimisticResponse):
    slot: str
    block: str
    previous_duty_dependent_root: str
    current_duty_dependent_root: str


class ChainReorgEvent(BeaconNodeEvent, ExecutionOptimisticResponse):
    slot: str
    depth: str
    old_head_block: str
    new_head_block: str


# Slashing events
class AttesterSlashingEventAttestation(msgspec.Struct):
    attesting_indices: list[str]


class AttesterSlashing(msgspec.Struct):
    attestation_1: AttesterSlashingEventAttestation
    attestation_2: AttesterSlashingEventAttestation


class AttesterSlashingEvent(BeaconNodeEvent, AttesterSlashing):
    pass


class ProposerSlashingEventMessage(msgspec.Struct):
    proposer_index: str


class ProposerSlashingEventData(msgspec.Struct):
    message: ProposerSlashingEventMessage


class ProposerSlashing(msgspec.Struct):
    signed_header_1: ProposerSlashingEventData
    signed_header_2: ProposerSlashingEventData


class ProposerSlashingEvent(BeaconNodeEvent, ProposerSlashing):
    pass
