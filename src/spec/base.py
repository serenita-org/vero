from dataclasses import dataclass, fields
from typing import Any, Self

from spec.common import Bytes4, Root, Uint64


def _to_obj(value: Any) -> Any:
    if hasattr(value, "to_obj"):
        return value.to_obj()
    if isinstance(value, dict):
        return {key: _to_obj(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_obj(item) for item in value]
    return value


class Version(Bytes4):
    pass


@dataclass(init=False)
class Genesis:
    genesis_time: Uint64
    genesis_validators_root: Root
    genesis_fork_version: Version

    def __init__(
        self,
        genesis_time: int | str,
        genesis_validators_root: bytes | str,
        genesis_fork_version: bytes | str,
    ) -> None:
        self.genesis_time = Uint64(genesis_time)
        self.genesis_validators_root = Root(genesis_validators_root)
        self.genesis_fork_version = Version(genesis_fork_version)

    @classmethod
    def from_obj(cls, obj: dict[str, Any]) -> Self:
        return cls(
            genesis_time=Uint64.from_obj(obj["genesis_time"]),
            genesis_validators_root=obj["genesis_validators_root"],
            genesis_fork_version=obj["genesis_fork_version"],
        )

    def to_obj(self) -> dict[str, Any]:
        return {
            field.name: _to_obj(getattr(self, field.name)) for field in fields(self)
        }


@dataclass
class SpecFulu:
    # Phase 0
    GENESIS_FORK_VERSION: Version
    SECONDS_PER_SLOT: Uint64
    SLOTS_PER_EPOCH: Uint64
    MAX_VALIDATORS_PER_COMMITTEE: Uint64
    MAX_COMMITTEES_PER_SLOT: Uint64
    MAX_PROPOSER_SLASHINGS: Uint64
    MAX_ATTESTER_SLASHINGS: Uint64
    MAX_ATTESTATIONS: Uint64
    MAX_DEPOSITS: Uint64
    MAX_VOLUNTARY_EXITS: Uint64

    # Altair
    ALTAIR_FORK_EPOCH: Uint64
    ALTAIR_FORK_VERSION: Version
    EPOCHS_PER_SYNC_COMMITTEE_PERIOD: Uint64
    SYNC_COMMITTEE_SIZE: Uint64

    # Bellatrix
    BELLATRIX_FORK_EPOCH: Uint64
    BELLATRIX_FORK_VERSION: Version
    BYTES_PER_LOGS_BLOOM: Uint64
    MAX_EXTRA_DATA_BYTES: Uint64
    MAX_TRANSACTIONS_PER_PAYLOAD: Uint64
    MAX_BYTES_PER_TRANSACTION: Uint64

    # Capella
    CAPELLA_FORK_EPOCH: Uint64
    CAPELLA_FORK_VERSION: Version
    MAX_WITHDRAWALS_PER_PAYLOAD: Uint64
    MAX_BLS_TO_EXECUTION_CHANGES: Uint64

    # Deneb
    DENEB_FORK_EPOCH: Uint64
    DENEB_FORK_VERSION: Version
    MAX_BLOB_COMMITMENTS_PER_BLOCK: Uint64
    FIELD_ELEMENTS_PER_BLOB: Uint64

    # Electra
    ELECTRA_FORK_EPOCH: Uint64
    ELECTRA_FORK_VERSION: Version
    MAX_DEPOSIT_REQUESTS_PER_PAYLOAD: Uint64
    MAX_WITHDRAWAL_REQUESTS_PER_PAYLOAD: Uint64
    MAX_CONSOLIDATION_REQUESTS_PER_PAYLOAD: Uint64
    MAX_ATTESTATIONS_ELECTRA: Uint64
    MAX_ATTESTER_SLASHINGS_ELECTRA: Uint64

    # Fulu
    FULU_FORK_EPOCH: Uint64
    FULU_FORK_VERSION: Version

    @classmethod
    def from_obj(cls, obj: dict[str, Any]) -> Self:
        values: dict[str, Any] = {}
        for field in fields(cls):
            if field.name not in obj:
                raise ValueError(f"Required field {field.name!r} missing from spec")
            values[field.name] = (
                Version(obj[field.name])
                if field.name.endswith("FORK_VERSION")
                else Uint64.from_obj(obj[field.name])
            )
        return cls(**values)

    def to_obj(self) -> dict[str, Any]:
        return {
            field.name: _to_obj(getattr(self, field.name)) for field in fields(self)
        }


def parse_spec(data: dict[str, str]) -> SpecFulu:
    return SpecFulu.from_obj(data)
