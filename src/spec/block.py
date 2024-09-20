from remerkleable.basic import uint256
from remerkleable.bitfields import Bitvector
from remerkleable.byte_arrays import ByteList, Bytes32, Bytes48, ByteVector
from remerkleable.complex import Container, List, Vector
from remerkleable.core import ObjType

from spec.attestation import Attestation, AttestationData
from spec.base import Spec
from spec.common import (
    BYTES_PER_LOGS_BLOOM,
    DEPOSIT_CONTRACT_TREE_DEPTH,
    MAX_ATTESTATIONS,
    MAX_ATTESTER_SLASHINGS,
    MAX_BLS_TO_EXECUTION_CHANGES,
    MAX_BYTES_PER_TRANSACTION,
    MAX_DEPOSITS,
    MAX_EXTRA_DATA_BYTES,
    MAX_PROPOSER_SLASHINGS,
    MAX_TRANSACTIONS_PER_PAYLOAD,
    MAX_VALIDATORS_PER_COMMITTEE,
    MAX_VOLUNTARY_EXITS,
    BLSPubkey,
    BLSSignature,
    Epoch,
    Hash32,
    Root,
    Slot,
    UInt64SerializedAsString,
    ValidatorIndex,
)


class Eth1Data(Container):
    deposit_root: Root
    deposit_count: UInt64SerializedAsString
    block_hash: Hash32


class Gwei(UInt64SerializedAsString):
    pass


class DepositData(Container):
    pubkey: BLSPubkey
    withdrawal_credentials: Bytes32
    amount: Gwei
    signature: BLSSignature  # Signing over DepositMessage


class Deposit(Container):
    proof: Vector[
        Bytes32,
        DEPOSIT_CONTRACT_TREE_DEPTH + 1,
    ]  # Merkle path to deposit root
    data: DepositData


class BeaconBlockHeader(Container):
    slot: Slot
    proposer_index: ValidatorIndex
    parent_root: Root
    state_root: Root
    body_root: Root


class SignedBeaconBlockHeader(Container):
    message: BeaconBlockHeader
    signature: BLSSignature


class ProposerSlashing(Container):
    signed_header_1: SignedBeaconBlockHeader
    signed_header_2: SignedBeaconBlockHeader


class IndexedAttestation(Container):
    attesting_indices: List[ValidatorIndex, MAX_VALIDATORS_PER_COMMITTEE]
    data: AttestationData
    signature: BLSSignature


class AttesterSlashing(Container):
    attestation_1: IndexedAttestation
    attestation_2: IndexedAttestation


class VoluntaryExit(Container):
    epoch: Epoch  # Earliest epoch when voluntary exit can be processed
    validator_index: ValidatorIndex


class SignedVoluntaryExit(Container):
    message: VoluntaryExit
    signature: BLSSignature


class Transaction(ByteList[MAX_BYTES_PER_TRANSACTION]):
    pass


class ExecutionAddress(ByteVector[20]):
    pass


class WithdrawalIndex(UInt64SerializedAsString):
    pass


class Withdrawal(Container):
    index: WithdrawalIndex
    validator_index: ValidatorIndex
    address: ExecutionAddress
    amount: Gwei


class BLSToExecutionChange(Container):
    validator_index: ValidatorIndex
    from_bls_pubkey: BLSPubkey
    to_execution_address: ExecutionAddress


class SignedBLSToExecutionChange(Container):
    message: BLSToExecutionChange
    signature: BLSSignature


class KZGCommitment(Bytes48):
    pass


class UInt256SerializedAsString(uint256):
    def to_obj(self) -> ObjType:
        return str(self)


class ExecutionPayloadHeaderDeneb(Container):
    # Execution block header fields
    parent_hash: Hash32
    fee_recipient: ExecutionAddress
    state_root: Bytes32
    receipts_root: Bytes32
    logs_bloom: ByteVector[BYTES_PER_LOGS_BLOOM]
    prev_randao: Bytes32
    block_number: UInt64SerializedAsString
    gas_limit: UInt64SerializedAsString
    gas_used: UInt64SerializedAsString
    timestamp: UInt64SerializedAsString
    extra_data: ByteList[MAX_EXTRA_DATA_BYTES]
    base_fee_per_gas: UInt256SerializedAsString
    # Extra payload fields
    block_hash: Hash32  # Hash of execution block
    transactions_root: Root
    withdrawals_root: Root
    blob_gas_used: UInt64SerializedAsString  # [New in Deneb:EIP4844]
    excess_blob_gas: UInt64SerializedAsString  # [New in Deneb:EIP4844]


# Dynamic block class creation
# to account for differing spec values across chains
class BeaconBlockClass:
    Deneb: Container
    DenebBlinded: Container

    @classmethod
    def initialize(
        cls,
        spec: Spec,
    ) -> None:
        class SyncAggregate(Container):
            sync_committee_bits: Bitvector[spec.SYNC_COMMITTEE_SIZE]
            sync_committee_signature: BLSSignature

        class ExecutionPayloadDeneb(Container):
            # Execution block header fields
            parent_hash: Hash32
            fee_recipient: ExecutionAddress  # 'beneficiary' in the yellow paper
            state_root: Bytes32
            receipts_root: Bytes32
            logs_bloom: ByteVector[BYTES_PER_LOGS_BLOOM]
            prev_randao: Bytes32  # 'difficulty' in the yellow paper
            block_number: UInt64SerializedAsString  # 'number' in the yellow paper
            gas_limit: UInt64SerializedAsString
            gas_used: UInt64SerializedAsString
            timestamp: UInt64SerializedAsString
            extra_data: ByteList[MAX_EXTRA_DATA_BYTES]
            base_fee_per_gas: UInt256SerializedAsString
            # Extra payload fields
            block_hash: Hash32  # Hash of execution block
            transactions: List[Transaction, MAX_TRANSACTIONS_PER_PAYLOAD]
            withdrawals: List[Withdrawal, spec.MAX_WITHDRAWALS_PER_PAYLOAD]
            blob_gas_used: UInt64SerializedAsString  # [New in Deneb:EIP4844]
            excess_blob_gas: UInt64SerializedAsString  # [New in Deneb:EIP4844]

        class BeaconBlockBodyDeneb(Container):
            randao_reveal: BLSSignature
            eth1_data: Eth1Data  # Eth1 data vote
            graffiti: Bytes32  # Arbitrary data
            # Operations
            proposer_slashings: List[ProposerSlashing, MAX_PROPOSER_SLASHINGS]
            attester_slashings: List[AttesterSlashing, MAX_ATTESTER_SLASHINGS]
            attestations: List[Attestation, MAX_ATTESTATIONS]
            deposits: List[Deposit, MAX_DEPOSITS]
            voluntary_exits: List[SignedVoluntaryExit, MAX_VOLUNTARY_EXITS]
            sync_aggregate: SyncAggregate  # [New in Altair]
            # Execution
            execution_payload: (
                ExecutionPayloadDeneb  # [New in Bellatrix, Modified in Deneb:EIP4844]
            )
            # Capella operations
            bls_to_execution_changes: List[
                SignedBLSToExecutionChange,
                MAX_BLS_TO_EXECUTION_CHANGES,
            ]  # [New in Capella]
            # Execution
            blob_kzg_commitments: List[
                KZGCommitment,
                spec.MAX_BLOB_COMMITMENTS_PER_BLOCK,
            ]  # [New in Deneb:EIP4844]

        class BlindedBeaconBlockBodyDeneb(Container):
            randao_reveal: BLSSignature
            eth1_data: Eth1Data  # Eth1 data vote
            graffiti: Bytes32  # Arbitrary data
            # Operations
            proposer_slashings: List[ProposerSlashing, MAX_PROPOSER_SLASHINGS]
            attester_slashings: List[AttesterSlashing, MAX_ATTESTER_SLASHINGS]
            attestations: List[Attestation, MAX_ATTESTATIONS]
            deposits: List[Deposit, MAX_DEPOSITS]
            voluntary_exits: List[SignedVoluntaryExit, MAX_VOLUNTARY_EXITS]
            sync_aggregate: SyncAggregate  # [New in Altair]
            # Execution
            execution_payload_header: (
                ExecutionPayloadHeaderDeneb
                # [New in Bellatrix, Modified in Deneb:EIP4844]
            )
            # Capella operations
            bls_to_execution_changes: List[
                SignedBLSToExecutionChange,
                MAX_BLS_TO_EXECUTION_CHANGES,
            ]  # [New in Capella]
            # Execution
            blob_kzg_commitments: List[
                KZGCommitment,
                spec.MAX_BLOB_COMMITMENTS_PER_BLOCK,
            ]  # [New in Deneb:EIP4844]

        class BeaconBlockDeneb(Container):
            slot: Slot
            proposer_index: ValidatorIndex
            parent_root: Root
            state_root: Root
            body: BeaconBlockBodyDeneb

        class BlindedBeaconBlockDeneb(Container):
            slot: Slot
            proposer_index: ValidatorIndex
            parent_root: Root
            state_root: Root
            body: BlindedBeaconBlockBodyDeneb

        cls.Deneb = BeaconBlockDeneb
        cls.DenebBlinded = BlindedBeaconBlockDeneb
