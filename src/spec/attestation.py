from remerkleable.bitfields import Bitlist
from remerkleable.complex import Container

from spec.common import (
    Slot,
    Root,
    BLSSignature,
    MAX_VALIDATORS_PER_COMMITTEE,
    Epoch,
    ValidatorIndex,
    UInt64SerializedAsString,
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


class Attestation(Container):
    aggregation_bits: Bitlist[MAX_VALIDATORS_PER_COMMITTEE]
    data: AttestationData
    signature: BLSSignature


class AggregateAndProof(Container):
    aggregator_index: ValidatorIndex
    aggregate: Attestation
    selection_proof: BLSSignature
