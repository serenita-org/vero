from remerkleable.bitfields import Bitvector
from remerkleable.complex import Container

from spec.base import SpecGloas
from spec.common import (
    BLSSignature,
    Root,
    Slot,
    UInt64SerializedAsString,
    ValidatorIndex,
)
from spec.constants import SYNC_COMMITTEE_SUBNET_COUNT


# Dynamic spec class creation
# to account for differing spec values across chains
class SpecSyncCommittee:
    Contribution: Container
    ContributionAndProof: Container

    @classmethod
    def initialize(
        cls,
        spec: SpecGloas,
    ) -> None:
        class SyncCommitteeContribution(Container):
            # Slot to which this contribution pertains
            slot: Slot
            # Block root for this contribution
            beacon_block_root: Root
            # The subcommittee this contribution pertains to out of the broader sync committee
            subcommittee_index: UInt64SerializedAsString
            # A bit is set if a signature from the validator at the corresponding
            # index in the subcommittee is present in the aggregate `signature`.
            aggregation_bits: Bitvector[
                spec.SYNC_COMMITTEE_SIZE // SYNC_COMMITTEE_SUBNET_COUNT
            ]
            # Signature by the validator(s) over the block root of `slot`
            signature: BLSSignature

        class SyncCommitteeContributionAndProof(Container):
            aggregator_index: ValidatorIndex
            contribution: SyncCommitteeContribution
            selection_proof: BLSSignature

        cls.Contribution = SyncCommitteeContribution
        cls.ContributionAndProof = SyncCommitteeContributionAndProof
