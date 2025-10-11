from __future__ import annotations

import msgspec

from schemas import SchemaBeaconAPI

PENDING_STATUSES = [
    SchemaBeaconAPI.ValidatorStatus.PENDING_INITIALIZED,
    SchemaBeaconAPI.ValidatorStatus.PENDING_QUEUED,
]

ACTIVE_STATUSES = [
    SchemaBeaconAPI.ValidatorStatus.ACTIVE_ONGOING,
    SchemaBeaconAPI.ValidatorStatus.ACTIVE_EXITING,
    SchemaBeaconAPI.ValidatorStatus.ACTIVE_SLASHED,
]

EXITED_STATUSES = [
    SchemaBeaconAPI.ValidatorStatus.EXITED_UNSLASHED,
    SchemaBeaconAPI.ValidatorStatus.EXITED_SLASHED,
]

WITHDRAWAL_STATUSES = [
    SchemaBeaconAPI.ValidatorStatus.WITHDRAWAL_POSSIBLE,
    SchemaBeaconAPI.ValidatorStatus.WITHDRAWAL_DONE,
]

SLASHED_STATUSES = [
    SchemaBeaconAPI.ValidatorStatus.ACTIVE_SLASHED,
    SchemaBeaconAPI.ValidatorStatus.EXITED_SLASHED,
]


class ValidatorIndexPubkey(msgspec.Struct, frozen=True):
    index: int
    pubkey: str
    status: SchemaBeaconAPI.ValidatorStatus
