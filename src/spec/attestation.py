from typing import TYPE_CHECKING

from remerkleable.bitfields import Bitlist, Bitvector
from remerkleable.complex import Container

from spec.common import (
    BLSSignature,
    Epoch,
    Root,
    Slot,
    UInt64SerializedAsString,
    ValidatorIndex,
)

if TYPE_CHECKING:
    from spec import Spec


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
    AttestationPhase0: Container
    IndexedAttestationPhase0: Container
    AggregateAndProofPhase0: Container
    AttestationElectra: Container
    IndexedAttestationElectra: Container
    AggregateAndProofElectra: Container

    @classmethod
    def initialize(
        cls,
        spec: "Spec",
    ) -> None:
        class AttestationPhase0(Container):
            aggregation_bits: Bitlist[spec.MAX_VALIDATORS_PER_COMMITTEE]
            data: AttestationData
            signature: BLSSignature

        class AggregateAndProofPhase0(Container):
            aggregator_index: ValidatorIndex
            aggregate: AttestationPhase0
            selection_proof: BLSSignature

        class AttestationElectra(Container):
            aggregation_bits: Bitlist[
                spec.MAX_VALIDATORS_PER_COMMITTEE * spec.MAX_COMMITTEES_PER_SLOT
            ]
            data: AttestationData
            signature: BLSSignature
            committee_bits: Bitvector[spec.MAX_COMMITTEES_PER_SLOT]

        class AggregateAndProofElectra(Container):
            aggregator_index: ValidatorIndex
            aggregate: AttestationElectra
            selection_proof: BLSSignature

        cls.AttestationPhase0 = AttestationPhase0
        cls.AggregateAndProofPhase0 = AggregateAndProofPhase0
        cls.AttestationElectra = AttestationElectra
        cls.AggregateAndProofElectra = AggregateAndProofElectra
