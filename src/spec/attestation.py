from remerkleable.bitfields import Bitlist, Bitvector
from remerkleable.complex import Container, List

from spec.common import (
    MAX_COMMITTEES_PER_SLOT,
    MAX_VALIDATORS_PER_COMMITTEE,
    BLSSignature,
    Epoch,
    Root,
    Slot,
    UInt64SerializedAsString,
    ValidatorIndex,
)


class CommitteeIndex(UInt64SerializedAsString):
    pass


class Checkpoint(Container):
    epoch: Epoch
    root: Root


class AttestationData(Container):
    slot: Slot
    index: CommitteeIndex
    # LMD GHOST vote
    beacon_block_root: Root
    # FFG vote
    source: Checkpoint
    target: Checkpoint


class AttestationPhase0(Container):
    aggregation_bits: Bitlist[MAX_VALIDATORS_PER_COMMITTEE]
    data: AttestationData
    signature: BLSSignature


class AttestationElectra(Container):
    aggregation_bits: Bitlist[MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT]
    data: AttestationData
    signature: BLSSignature
    committee_bits: Bitvector[MAX_COMMITTEES_PER_SLOT]


# TODO Post-Electra cleanup
class AggregateAndProof(Container):
    aggregator_index: ValidatorIndex
    aggregate: AttestationPhase0
    selection_proof: BLSSignature


class AggregateAndProofV2(Container):
    aggregator_index: ValidatorIndex
    aggregate: AttestationElectra
    selection_proof: BLSSignature


class IndexedAttestationPhase0(Container):
    attesting_indices: List[ValidatorIndex, MAX_VALIDATORS_PER_COMMITTEE]
    data: AttestationData
    signature: BLSSignature


class IndexedAttestationElectra(Container):
    attesting_indices: List[
        ValidatorIndex, MAX_VALIDATORS_PER_COMMITTEE * MAX_COMMITTEES_PER_SLOT
    ]
    data: AttestationData
    signature: BLSSignature
