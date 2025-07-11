from enum import Enum
from typing import TypeVar

import msgspec


class SigningRequestType(Enum):
    AGGREGATE_AND_PROOF = "AGGREGATE_AND_PROOF"
    AGGREGATE_AND_PROOF_V2 = "AGGREGATE_AND_PROOF_V2"
    AGGREGATION_SLOT = "AGGREGATION_SLOT"
    ATTESTATION = "ATTESTATION"
    BLOCK_V2 = "BLOCK_V2"
    RANDAO_REVEAL = "RANDAO_REVEAL"
    SYNC_COMMITTEE_CONTRIBUTION_AND_PROOF = "SYNC_COMMITTEE_CONTRIBUTION_AND_PROOF"
    SYNC_COMMITTEE_MESSAGE = "SYNC_COMMITTEE_MESSAGE"
    SYNC_COMMITTEE_SELECTION_PROOF = "SYNC_COMMITTEE_SELECTION_PROOF"
    VALIDATOR_REGISTRATION = "VALIDATOR_REGISTRATION"
    VOLUNTARY_EXIT = "VOLUNTARY_EXIT"


SignableMessageT = TypeVar("SignableMessageT", bound="SignableMessage")


class SignableMessage(msgspec.Struct):
    type: SigningRequestType


class Fork(msgspec.Struct):
    previous_version: str
    current_version: str
    epoch: str


class ForkInfo(msgspec.Struct):
    fork: Fork
    genesis_validators_root: str


class SignableMessageWithForkInfo(SignableMessage, kw_only=True):
    fork_info: ForkInfo


class AttestationSignableMessage(SignableMessageWithForkInfo, kw_only=True):
    type: SigningRequestType = SigningRequestType.ATTESTATION
    attestation: dict  # type: ignore[type-arg]


class Slot(msgspec.Struct):
    slot: str


class AggregationSlotSignableMessage(SignableMessageWithForkInfo, kw_only=True):
    type: SigningRequestType = SigningRequestType.AGGREGATION_SLOT
    aggregation_slot: Slot


class AggregateAndProofSignableMessage(SignableMessageWithForkInfo, kw_only=True):
    type: SigningRequestType = SigningRequestType.AGGREGATE_AND_PROOF
    aggregate_and_proof: dict  # type: ignore[type-arg]


class AggregateAndProofV2SignableMessage(SignableMessageWithForkInfo, kw_only=True):
    type: SigningRequestType = SigningRequestType.AGGREGATE_AND_PROOF_V2
    aggregate_and_proof: dict  # type: ignore[type-arg]


class RandaoReveal(msgspec.Struct):
    epoch: str


class RandaoRevealSignableMessage(SignableMessageWithForkInfo, kw_only=True):
    type: SigningRequestType = SigningRequestType.RANDAO_REVEAL
    randao_reveal: RandaoReveal


class BeaconBlockHeader(msgspec.Struct):
    slot: str
    proposer_index: str
    parent_root: str
    state_root: str
    body_root: str


class BeaconBlockVersion(Enum):
    ELECTRA = "ELECTRA"


class BeaconBlock(msgspec.Struct):
    version: BeaconBlockVersion
    block_header: BeaconBlockHeader


class BeaconBlockV2SignableMessage(SignableMessageWithForkInfo, kw_only=True):
    type: SigningRequestType = SigningRequestType.BLOCK_V2
    beacon_block: BeaconBlock


class SyncCommitteeMessage(msgspec.Struct):
    beacon_block_root: str
    slot: str


class SyncCommitteeMessageSignableMessage(SignableMessageWithForkInfo, kw_only=True):
    type: SigningRequestType = SigningRequestType.SYNC_COMMITTEE_MESSAGE
    sync_committee_message: SyncCommitteeMessage


class SyncAggregatorSelectionData(msgspec.Struct):
    slot: str
    subcommittee_index: str


class SyncCommitteeSelectionProofSignableMessage(
    SignableMessageWithForkInfo, kw_only=True
):
    type: SigningRequestType = SigningRequestType.SYNC_COMMITTEE_SELECTION_PROOF
    sync_aggregator_selection_data: SyncAggregatorSelectionData


class SyncCommitteeContributionAndProofSignableMessage(
    SignableMessageWithForkInfo, kw_only=True
):
    type: SigningRequestType = SigningRequestType.SYNC_COMMITTEE_CONTRIBUTION_AND_PROOF
    contribution_and_proof: dict  # type: ignore[type-arg]


class ValidatorRegistration(msgspec.Struct):
    fee_recipient: str
    gas_limit: str
    timestamp: str
    pubkey: str


class ValidatorRegistrationSignableMessage(SignableMessage, kw_only=True):
    type: SigningRequestType = SigningRequestType.VALIDATOR_REGISTRATION
    validator_registration: ValidatorRegistration


class VoluntaryExit(msgspec.Struct):
    epoch: str
    validator_index: str


class VoluntaryExitSignableMessage(SignableMessageWithForkInfo, kw_only=True):
    type: SigningRequestType = SigningRequestType.VOLUNTARY_EXIT
    voluntary_exit: VoluntaryExit
