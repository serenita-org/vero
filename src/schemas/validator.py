from enum import Enum
from pydantic import BaseModel, ConfigDict


class ValidatorStatus(Enum):
    ACTIVE_ONGOING = "active_ongoing"
    ACTIVE_EXITING = "active_exiting"
    ACTIVE_SLASHED = "active_slashed"
    PENDING_INITIALIZED = "pending_initialized"
    PENDING_QUEUED = "pending_queued"


ACTIVE_STATUSES = [
    ValidatorStatus.ACTIVE_ONGOING,
    ValidatorStatus.ACTIVE_EXITING,
]

PENDING_STATUSES = [
    ValidatorStatus.PENDING_INITIALIZED,
    ValidatorStatus.PENDING_QUEUED,
]

SLASHED_STATUSES = [
    ValidatorStatus.ACTIVE_SLASHED,
]


class ValidatorIndexPubkey(BaseModel):
    index: int
    pubkey: str
    status: ValidatorStatus

    model_config = ConfigDict(frozen=True)
