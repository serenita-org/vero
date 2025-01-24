from .attestation import SpecAttestation
from .base import Spec
from .block import SpecBeaconBlock
from .sync_committee import SpecSyncCommittee

__all__ = [
    "Spec",
    "SpecAttestation",
    "SpecBeaconBlock",
    "SpecSyncCommittee",
]
