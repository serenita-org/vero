from dataclasses import dataclass, fields
from typing import Any, Self

from spec.common import Bytes4, Root, UInt64SerializedAsString, to_obj


class Version(Bytes4):
    pass


@dataclass(init=False)
class Genesis:
    genesis_time: UInt64SerializedAsString
    genesis_validators_root: Root
    genesis_fork_version: Version

    def __init__(
        self,
        genesis_time: int | str,
        genesis_validators_root: bytes | str,
        genesis_fork_version: bytes | str,
    ) -> None:
        self.genesis_time = UInt64SerializedAsString(genesis_time)
        self.genesis_validators_root = Root(genesis_validators_root)
        self.genesis_fork_version = Version(genesis_fork_version)

    @classmethod
    def from_obj(cls, obj: dict[str, Any]) -> Self:
        return cls(**obj)

    def to_obj(self) -> dict[str, Any]:
        return {field.name: to_obj(getattr(self, field.name)) for field in fields(self)}


@dataclass
class SpecFulu:
    SECONDS_PER_SLOT: UInt64SerializedAsString
    SLOTS_PER_EPOCH: UInt64SerializedAsString
    MAX_VALIDATORS_PER_COMMITTEE: UInt64SerializedAsString
    MAX_COMMITTEES_PER_SLOT: UInt64SerializedAsString
    GENESIS_FORK_VERSION: Version
    MAX_PROPOSER_SLASHINGS: UInt64SerializedAsString
    MAX_ATTESTER_SLASHINGS: UInt64SerializedAsString
    MAX_ATTESTATIONS: UInt64SerializedAsString
    MAX_DEPOSITS: UInt64SerializedAsString
    MAX_VOLUNTARY_EXITS: UInt64SerializedAsString
    EPOCHS_PER_SYNC_COMMITTEE_PERIOD: UInt64SerializedAsString
    SYNC_COMMITTEE_SIZE: UInt64SerializedAsString
    ALTAIR_FORK_EPOCH: UInt64SerializedAsString
    ALTAIR_FORK_VERSION: Version
    BELLATRIX_FORK_EPOCH: UInt64SerializedAsString
    BELLATRIX_FORK_VERSION: Version
    BYTES_PER_LOGS_BLOOM: UInt64SerializedAsString
    MAX_EXTRA_DATA_BYTES: UInt64SerializedAsString
    MAX_TRANSACTIONS_PER_PAYLOAD: UInt64SerializedAsString
    MAX_BYTES_PER_TRANSACTION: UInt64SerializedAsString
    MAX_WITHDRAWALS_PER_PAYLOAD: UInt64SerializedAsString
    CAPELLA_FORK_EPOCH: UInt64SerializedAsString
    CAPELLA_FORK_VERSION: Version
    MAX_BLS_TO_EXECUTION_CHANGES: UInt64SerializedAsString
    MAX_BLOB_COMMITMENTS_PER_BLOCK: UInt64SerializedAsString
    DENEB_FORK_EPOCH: UInt64SerializedAsString
    DENEB_FORK_VERSION: Version
    FIELD_ELEMENTS_PER_BLOB: UInt64SerializedAsString
    ELECTRA_FORK_EPOCH: UInt64SerializedAsString
    ELECTRA_FORK_VERSION: Version
    MAX_DEPOSIT_REQUESTS_PER_PAYLOAD: UInt64SerializedAsString
    MAX_WITHDRAWAL_REQUESTS_PER_PAYLOAD: UInt64SerializedAsString
    MAX_CONSOLIDATION_REQUESTS_PER_PAYLOAD: UInt64SerializedAsString
    MAX_ATTESTATIONS_ELECTRA: UInt64SerializedAsString
    MAX_ATTESTER_SLASHINGS_ELECTRA: UInt64SerializedAsString
    FULU_FORK_EPOCH: UInt64SerializedAsString
    FULU_FORK_VERSION: Version

    @classmethod
    def from_obj(cls, obj: dict[str, Any]) -> Self:
        values: dict[str, Any] = {}
        for field in fields(cls):
            if field.name not in obj:
                raise ValueError(f"Required field {field.name!r} missing from spec")
            converter = (
                Version
                if field.name.endswith("FORK_VERSION")
                else UInt64SerializedAsString
            )
            values[field.name] = converter(obj[field.name])
        return cls(**values)

    def to_obj(self) -> dict[str, Any]:
        return {field.name: to_obj(getattr(self, field.name)) for field in fields(self)}


def parse_spec(data: dict[str, str]) -> SpecFulu:
    return SpecFulu.from_obj(data)
