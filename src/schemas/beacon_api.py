"""
API response models for the Beacon Node API.

Useful links:

https://github.com/ethereum/beacon-APIs
https://ethereum.github.io/beacon-APIs/

https://docs.nodereal.io/reference/eventstream
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, field_serializer


class ExecutionOptimisticResponse(BaseModel):
    execution_optimistic: bool


class AttesterDuty(BaseModel):
    pubkey: str
    validator_index: int
    committee_index: int
    committee_length: int
    committees_at_slot: int
    validator_committee_index: int
    slot: int


class AttesterDutyWithSelectionProof(AttesterDuty):
    is_aggregator: bool
    selection_proof: bytes

    model_config = ConfigDict(frozen=True)


class GetAttesterDutiesResponse(ExecutionOptimisticResponse):
    dependent_root: str
    data: list[AttesterDuty]


class ProposerDuty(BaseModel):
    pubkey: str
    validator_index: int
    slot: int

    model_config = ConfigDict(frozen=True)


class GetProposerDutiesResponse(ExecutionOptimisticResponse):
    dependent_root: str
    data: list[ProposerDuty]


class SyncDuty(BaseModel):
    pubkey: str
    validator_index: int
    validator_sync_committee_indices: list[int]


class SyncDutySubCommitteeSelectionProof(BaseModel):
    slot: int
    subcommittee_index: int
    is_aggregator: bool
    selection_proof: bytes


class SyncDutyWithSelectionProofs(SyncDuty):
    selection_proofs: list[SyncDutySubCommitteeSelectionProof]


class GetSyncDutiesResponse(ExecutionOptimisticResponse):
    data: list[SyncDuty]


class BlockRoot(BaseModel):
    root: str


class GetBlockRootResponse(ExecutionOptimisticResponse):
    finalized: bool
    data: BlockRoot


class BeaconNodeEvent(BaseModel):
    pass


class HeadEvent(BeaconNodeEvent, ExecutionOptimisticResponse):
    slot: int
    block: str
    state: str
    epoch_transition: bool
    previous_duty_dependent_root: str
    current_duty_dependent_root: str


class ChainReorgEvent(BeaconNodeEvent, ExecutionOptimisticResponse):
    slot: int
    depth: int
    old_head_block: str
    new_head_block: str
    old_head_state: str
    new_head_state: str
    epoch: int


class AttesterSlashingEventAttestation(BaseModel):
    attesting_indices: list[int]
    data: dict
    signature: bytes


class AttesterSlashing(BaseModel):
    attestation_1: AttesterSlashingEventAttestation
    attestation_2: AttesterSlashingEventAttestation


class AttesterSlashingEvent(BeaconNodeEvent, AttesterSlashing):
    pass


class ProposerSlashingEventMessage(BaseModel):
    slot: int
    proposer_index: int
    parent_root: str
    state_root: str
    body_root: str


class ProposerSlashingEventData(BaseModel):
    message: ProposerSlashingEventMessage
    signature: bytes


class ProposerSlashing(BaseModel):
    signed_header_1: ProposerSlashingEventData
    signed_header_2: ProposerSlashingEventData


class ProposerSlashingEvent(BeaconNodeEvent, ProposerSlashing):
    pass


class BeaconBlockVersion(Enum):
    DENEB = "deneb"


class ProduceBlockV3Response(BaseModel):
    version: BeaconBlockVersion
    execution_payload_blinded: bool
    execution_payload_value: int
    consensus_block_value: int
    data: dict

    # Intentionally not using ConfigDict(use_enum_values=True)
    # here for version so that we can more easily work with
    # the Enum in the rest of the codebase
    @field_serializer("version")
    def serialize_version(self, version: BeaconBlockVersion, _info):
        return version.value
