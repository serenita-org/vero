import msgspec

from schemas import SchemaBeaconAPI

ACTIVE_STATUSES = [
    SchemaBeaconAPI.ValidatorStatus.ACTIVE_ONGOING,
    SchemaBeaconAPI.ValidatorStatus.ACTIVE_EXITING,
]

PENDING_STATUSES = [
    SchemaBeaconAPI.ValidatorStatus.PENDING_INITIALIZED,
    SchemaBeaconAPI.ValidatorStatus.PENDING_QUEUED,
]

SLASHED_STATUSES = [
    SchemaBeaconAPI.ValidatorStatus.ACTIVE_SLASHED,
]


class ValidatorIndexPubkey(msgspec.Struct, frozen=True):
    index: int
    pubkey: str
    status: SchemaBeaconAPI.ValidatorStatus
