import copy
from typing import Self

from remerkleable.byte_arrays import Bytes4
from remerkleable.complex import Container
from remerkleable.core import ObjParseException, ObjType

from spec.common import Root, UInt64SerializedAsString


class Version(Bytes4):
    pass


class Fork(Container):
    previous_version: Version
    current_version: Version
    epoch: UInt64SerializedAsString


class Genesis(Container):
    genesis_time: UInt64SerializedAsString
    genesis_validators_root: Root
    genesis_fork_version: Version


class SpecFulu(Container):
    # Phase 0
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

    # Altair
    EPOCHS_PER_SYNC_COMMITTEE_PERIOD: UInt64SerializedAsString
    SYNC_COMMITTEE_SIZE: UInt64SerializedAsString
    ALTAIR_FORK_EPOCH: UInt64SerializedAsString
    ALTAIR_FORK_VERSION: Version

    # Bellatrix
    BELLATRIX_FORK_EPOCH: UInt64SerializedAsString
    BELLATRIX_FORK_VERSION: Version

    BYTES_PER_LOGS_BLOOM: UInt64SerializedAsString
    MAX_EXTRA_DATA_BYTES: UInt64SerializedAsString
    MAX_TRANSACTIONS_PER_PAYLOAD: UInt64SerializedAsString
    MAX_BYTES_PER_TRANSACTION: UInt64SerializedAsString

    # Capella
    MAX_WITHDRAWALS_PER_PAYLOAD: UInt64SerializedAsString
    CAPELLA_FORK_EPOCH: UInt64SerializedAsString
    CAPELLA_FORK_VERSION: Version
    MAX_BLS_TO_EXECUTION_CHANGES: UInt64SerializedAsString

    # Deneb
    MAX_BLOB_COMMITMENTS_PER_BLOCK: UInt64SerializedAsString
    DENEB_FORK_EPOCH: UInt64SerializedAsString
    DENEB_FORK_VERSION: Version
    FIELD_ELEMENTS_PER_BLOB: UInt64SerializedAsString

    # Electra
    ELECTRA_FORK_EPOCH: UInt64SerializedAsString
    ELECTRA_FORK_VERSION: Version
    MAX_DEPOSIT_REQUESTS_PER_PAYLOAD: UInt64SerializedAsString
    MAX_WITHDRAWAL_REQUESTS_PER_PAYLOAD: UInt64SerializedAsString
    MAX_CONSOLIDATION_REQUESTS_PER_PAYLOAD: UInt64SerializedAsString
    MAX_ATTESTATIONS_ELECTRA: UInt64SerializedAsString
    MAX_ATTESTER_SLASHINGS_ELECTRA: UInt64SerializedAsString

    # Fulu
    FULU_FORK_EPOCH: UInt64SerializedAsString
    FULU_FORK_VERSION: Version

    @classmethod
    def from_obj(cls, obj: ObjType) -> Self:
        if not isinstance(obj, dict):
            raise ObjParseException(f"obj '{obj}' is not a dict")

        # Create a copy since we manipulate the dict
        _obj = copy.deepcopy(obj)

        # Remove extra keys/fields
        fields = cls.fields()
        for k in list(_obj.keys()):
            if k not in fields:
                del _obj[k]

        # Check if all required fields have a value
        if any(field not in _obj for field in fields):
            missing = set(fields.keys()) - set(_obj.keys())
            raise ObjParseException(
                f"Required field(s) ({missing}) missing from {_obj}"
            )

        return cls(**{k: fields[k].from_obj(v) for k, v in _obj.items()})


def parse_spec(data: dict[str, str]) -> SpecFulu:
    return SpecFulu.from_obj(data)
