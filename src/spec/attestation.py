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
    from spec.base import SpecElectra


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
    AttestationElectra: Container
    IndexedAttestationElectra: Container
    AggregateAndProofElectra: Container

    @classmethod
    def initialize(
        cls,
        spec: "SpecElectra",
    ) -> None:
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

        cls.AttestationElectra = AttestationElectra
        cls.AggregateAndProofElectra = AggregateAndProofElectra
