from enum import Enum

from pydantic import BaseModel, ConfigDict, field_serializer

from schemas import SchemaBeaconAPI


class ForkInfo(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True)
    fork: dict[str, str]
    genesis_validators_root: str


class SigningRequestType(Enum):
    AGGREGATE_AND_PROOF = "AGGREGATE_AND_PROOF"
    AGGREGATION_SLOT = "AGGREGATION_SLOT"
    ATTESTATION = "ATTESTATION"
    BLOCK_V2 = "BLOCK_V2"
    RANDAO_REVEAL = "RANDAO_REVEAL"
    SYNC_COMMITTEE_CONTRIBUTION_AND_PROOF = "SYNC_COMMITTEE_CONTRIBUTION_AND_PROOF"
    SYNC_COMMITTEE_MESSAGE = "SYNC_COMMITTEE_MESSAGE"
    SYNC_COMMITTEE_SELECTION_PROOF = "SYNC_COMMITTEE_SELECTION_PROOF"
    VALIDATOR_REGISTRATION = "VALIDATOR_REGISTRATION"


class SignableMessage(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    type: SigningRequestType


class SignableMessageWithForkInfo(SignableMessage):
    fork_info: ForkInfo


class AttestationSignableMessage(SignableMessageWithForkInfo):
    type: SigningRequestType = SigningRequestType.ATTESTATION
    attestation: dict


class Slot(BaseModel):
    slot: int


class AggregationSlotSignableMessage(SignableMessageWithForkInfo):
    type: SigningRequestType = SigningRequestType.AGGREGATION_SLOT
    aggregation_slot: Slot


class AggregateAndProofSignableMessage(SignableMessageWithForkInfo):
    type: SigningRequestType = SigningRequestType.AGGREGATE_AND_PROOF
    aggregate_and_proof: dict


class RandaoReveal(BaseModel):
    epoch: int


class RandaoRevealSignableMessage(SignableMessageWithForkInfo):
    type: SigningRequestType = SigningRequestType.RANDAO_REVEAL
    randao_reveal: RandaoReveal


class BeaconBlockHeader(BaseModel):
    slot: int
    proposer_index: int
    parent_root: str
    state_root: str
    body_root: str


class BeaconBlock(BaseModel):
    version: SchemaBeaconAPI.BeaconBlockVersion
    block_header: BeaconBlockHeader

    @field_serializer("version")
    def serialize_version(self, version: Enum, _info):
        return version.value.upper()


class BeaconBlockV2SignableMessage(SignableMessageWithForkInfo):
    type: SigningRequestType = SigningRequestType.BLOCK_V2
    beacon_block: BeaconBlock


class SyncCommitteeMessage(BaseModel):
    beacon_block_root: str
    slot: int


class SyncCommitteeMessageSignableMessage(SignableMessageWithForkInfo):
    type: SigningRequestType = SigningRequestType.SYNC_COMMITTEE_MESSAGE
    sync_committee_message: SyncCommitteeMessage


class SyncAggregatorSelectionData(BaseModel):
    slot: int
    subcommittee_index: int


class SyncCommitteeSelectionProofSignableMessage(SignableMessageWithForkInfo):
    type: SigningRequestType = SigningRequestType.SYNC_COMMITTEE_SELECTION_PROOF
    sync_aggregator_selection_data: SyncAggregatorSelectionData


class SyncCommitteeContributionAndProofSignableMessage(SignableMessageWithForkInfo):
    type: SigningRequestType = SigningRequestType.SYNC_COMMITTEE_CONTRIBUTION_AND_PROOF
    contribution_and_proof: dict


class ValidatorRegistration(BaseModel):
    fee_recipient: str
    gas_limit: str
    timestamp: str
    pubkey: str


class ValidatorRegistrationSignableMessage(SignableMessage):
    type: SigningRequestType = SigningRequestType.VALIDATOR_REGISTRATION
    validator_registration: ValidatorRegistration
