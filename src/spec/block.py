from remerkleable.bitfields import Bitvector
from remerkleable.byte_arrays import ByteList, Bytes32, Bytes48, ByteVector
from remerkleable.complex import Container, List, Vector

from spec.attestation import (
    AttestationData,
    SpecAttestation,
)
from spec.base import SpecFulu
from spec.common import (
    BLSPubkey,
    BLSSignature,
    Epoch,
    Hash32,
    Root,
    Slot,
    UInt64SerializedAsString,
    UInt256SerializedAsString,
    ValidatorIndex,
)
from spec.constants import BYTES_PER_FIELD_ELEMENT, DEPOSIT_CONTRACT_TREE_DEPTH


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


class VoluntaryExit(Container):
    epoch: Epoch  # Earliest epoch when voluntary exit can be processed
    validator_index: ValidatorIndex


class SignedVoluntaryExit(Container):
    message: VoluntaryExit
    signature: BLSSignature


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


class DepositRequest(Container):
    pubkey: BLSPubkey
    withdrawal_credentials: Bytes32
    amount: Gwei
    signature: BLSSignature
    index: UInt64SerializedAsString


class WithdrawalRequest(Container):
    source_address: ExecutionAddress
    validator_pubkey: BLSPubkey
    amount: Gwei


class ConsolidationRequest(Container):
    source_address: ExecutionAddress
    source_pubkey: BLSPubkey
    target_pubkey: BLSPubkey


class KZGProof(Bytes48):
    pass


# Dynamic spec class creation
# to account for differing spec values across chains
class SpecBeaconBlock:
    ElectraBlockSigned: Container
    ElectraBlockContents: Container
    ElectraBlockContentsSigned: Container
    ElectraBlindedBlock: Container
    ElectraBlindedBlockSigned: Container

    @classmethod
    def initialize(
        cls,
        spec: SpecFulu,
    ) -> None:
        class SyncAggregate(Container):
            sync_committee_bits: Bitvector[spec.SYNC_COMMITTEE_SIZE]
            sync_committee_signature: BLSSignature

        class Transaction(ByteList[spec.MAX_BYTES_PER_TRANSACTION]):  # type: ignore[name-defined]
            pass

        class ExecutionPayloadV3Header(Container):
            # Execution block header fields
            parent_hash: Hash32
            fee_recipient: ExecutionAddress
            state_root: Bytes32
            receipts_root: Bytes32
            logs_bloom: ByteVector[spec.BYTES_PER_LOGS_BLOOM]
            prev_randao: Bytes32
            block_number: UInt64SerializedAsString
            gas_limit: UInt64SerializedAsString
            gas_used: UInt64SerializedAsString
            timestamp: UInt64SerializedAsString
            extra_data: ByteList[spec.MAX_EXTRA_DATA_BYTES]
            base_fee_per_gas: UInt256SerializedAsString
            # Extra payload fields
            block_hash: Hash32  # Hash of execution block
            transactions_root: Root
            withdrawals_root: Root
            blob_gas_used: UInt64SerializedAsString  # [New in Deneb:EIP4844]
            excess_blob_gas: UInt64SerializedAsString  # [New in Deneb:EIP4844]

        class ExecutionPayloadV3(Container):
            # Execution block header fields
            parent_hash: Hash32
            fee_recipient: ExecutionAddress  # 'beneficiary' in the yellow paper
            state_root: Bytes32
            receipts_root: Bytes32
            logs_bloom: ByteVector[spec.BYTES_PER_LOGS_BLOOM]
            prev_randao: Bytes32  # 'difficulty' in the yellow paper
            block_number: UInt64SerializedAsString  # 'number' in the yellow paper
            gas_limit: UInt64SerializedAsString
            gas_used: UInt64SerializedAsString
            timestamp: UInt64SerializedAsString
            extra_data: ByteList[spec.MAX_EXTRA_DATA_BYTES]
            base_fee_per_gas: UInt256SerializedAsString
            # Extra payload fields
            block_hash: Hash32  # Hash of execution block
            transactions: List[Transaction, spec.MAX_TRANSACTIONS_PER_PAYLOAD]
            withdrawals: List[Withdrawal, spec.MAX_WITHDRAWALS_PER_PAYLOAD]
            blob_gas_used: UInt64SerializedAsString  # [New in Deneb:EIP4844]
            excess_blob_gas: UInt64SerializedAsString  # [New in Deneb:EIP4844]

        class IndexedAttestationElectra(Container):
            attesting_indices: List[
                ValidatorIndex,
                spec.MAX_VALIDATORS_PER_COMMITTEE * spec.MAX_COMMITTEES_PER_SLOT,
            ]
            data: AttestationData
            signature: BLSSignature

        class AttesterSlashingElectra(Container):
            attestation_1: IndexedAttestationElectra
            attestation_2: IndexedAttestationElectra

        class ExecutionRequests(Container):
            deposits: List[
                DepositRequest, spec.MAX_DEPOSIT_REQUESTS_PER_PAYLOAD
            ]  # [New in Electra:EIP6110]
            withdrawals: List[
                WithdrawalRequest, spec.MAX_WITHDRAWAL_REQUESTS_PER_PAYLOAD
            ]  # [New in Electra:EIP7002:EIP7251]
            consolidations: List[
                ConsolidationRequest, spec.MAX_CONSOLIDATION_REQUESTS_PER_PAYLOAD
            ]  # [New in Electra:EIP7251]

        class BeaconBlockBodyElectra(Container):
            randao_reveal: BLSSignature
            eth1_data: Eth1Data  # Eth1 data vote
            graffiti: Bytes32  # Arbitrary data
            # Operations
            proposer_slashings: List[ProposerSlashing, spec.MAX_PROPOSER_SLASHINGS]
            attester_slashings: List[
                AttesterSlashingElectra, spec.MAX_ATTESTER_SLASHINGS_ELECTRA
            ]  # [Modified in Electra:EIP7549]
            attestations: List[
                SpecAttestation.AttestationElectra, spec.MAX_ATTESTATIONS_ELECTRA
            ]  # [Modified in Electra:EIP7549]
            deposits: List[Deposit, spec.MAX_DEPOSITS]
            voluntary_exits: List[SignedVoluntaryExit, spec.MAX_VOLUNTARY_EXITS]
            sync_aggregate: SyncAggregate
            # Execution
            execution_payload: ExecutionPayloadV3
            # Capella operations
            bls_to_execution_changes: List[
                SignedBLSToExecutionChange,
                spec.MAX_BLS_TO_EXECUTION_CHANGES,
            ]  # [New in Capella]
            # Deneb
            blob_kzg_commitments: List[
                KZGCommitment,
                spec.MAX_BLOB_COMMITMENTS_PER_BLOCK,
            ]  # [New in Deneb:EIP4844]
            # Electra
            execution_requests: ExecutionRequests  # [New in Electra]

        class BlindedBeaconBlockBodyElectra(Container):
            randao_reveal: BLSSignature
            eth1_data: Eth1Data  # Eth1 data vote
            graffiti: Bytes32  # Arbitrary data
            # Operations
            proposer_slashings: List[ProposerSlashing, spec.MAX_PROPOSER_SLASHINGS]
            attester_slashings: List[
                AttesterSlashingElectra, spec.MAX_ATTESTER_SLASHINGS_ELECTRA
            ]  # [Modified in Electra:EIP7549]
            attestations: List[
                SpecAttestation.AttestationElectra, spec.MAX_ATTESTATIONS_ELECTRA
            ]  # [Modified in Electra:EIP7549]
            deposits: List[Deposit, spec.MAX_DEPOSITS]
            voluntary_exits: List[SignedVoluntaryExit, spec.MAX_VOLUNTARY_EXITS]
            sync_aggregate: SyncAggregate  # [New in Altair]
            # Execution
            execution_payload_header: (
                ExecutionPayloadV3Header
                # [New in Bellatrix, Modified in Deneb:EIP4844]
            )
            # Capella operations
            bls_to_execution_changes: List[
                SignedBLSToExecutionChange,
                spec.MAX_BLS_TO_EXECUTION_CHANGES,
            ]  # [New in Capella]
            # Deneb
            blob_kzg_commitments: List[
                KZGCommitment,
                spec.MAX_BLOB_COMMITMENTS_PER_BLOCK,
            ]  # [New in Deneb:EIP4844]
            # Electra
            execution_requests: ExecutionRequests  # [New in Electra]

        class Blob(ByteVector[BYTES_PER_FIELD_ELEMENT * spec.FIELD_ELEMENTS_PER_BLOB]):  # type: ignore[misc]
            pass

        class BeaconBlockElectra(Container):
            slot: Slot
            proposer_index: ValidatorIndex
            parent_root: Root
            state_root: Root
            body: BeaconBlockBodyElectra

        class BlockContentsElectra(Container):
            block: BeaconBlockElectra
            kzg_proofs: List[KZGProof, spec.MAX_BLOB_COMMITMENTS_PER_BLOCK]
            blobs: List[Blob, spec.MAX_BLOB_COMMITMENTS_PER_BLOCK]

        class SignedBeaconBlockElectra(Container):
            message: BeaconBlockElectra
            signature: BLSSignature

        class SignedBlockContentsElectra(Container):
            signed_block: SignedBeaconBlockElectra
            kzg_proofs: List[KZGProof, spec.MAX_BLOB_COMMITMENTS_PER_BLOCK]
            blobs: List[Blob, spec.MAX_BLOB_COMMITMENTS_PER_BLOCK]

        class BlindedBeaconBlockElectra(Container):
            slot: Slot
            proposer_index: ValidatorIndex
            parent_root: Root
            state_root: Root
            body: BlindedBeaconBlockBodyElectra

        class SignedBlindedBeaconBlockElectra(Container):
            message: BlindedBeaconBlockElectra
            signature: BLSSignature

        cls.ElectraBlockSigned = SignedBeaconBlockElectra
        cls.ElectraBlockContents = BlockContentsElectra
        cls.ElectraBlockContentsSigned = SignedBlockContentsElectra
        cls.ElectraBlindedBlock = BlindedBeaconBlockElectra
        cls.ElectraBlindedBlockSigned = SignedBlindedBeaconBlockElectra
