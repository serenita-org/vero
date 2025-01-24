from remerkleable.bitfields import Bitlist
from remerkleable.complex import Container

from spec.base import Spec
from spec.common import (
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


# Dynamic spec class creation
# to account for differing spec values across chains
class SpecAttestation:
    AttestationDeneb: Container
    AggregateAndProofDeneb: Container

    @classmethod
    def initialize(
        cls,
        spec: Spec,
    ) -> None:
        class Attestation(Container):
            aggregation_bits: Bitlist[spec.MAX_VALIDATORS_PER_COMMITTEE]
            data: AttestationData
            signature: BLSSignature

        class AggregateAndProof(Container):
            aggregator_index: ValidatorIndex
            aggregate: Attestation
            selection_proof: BLSSignature

        cls.AttestationDeneb = Attestation
        cls.AggregateAndProofDeneb = AggregateAndProof
