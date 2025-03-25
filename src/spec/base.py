import copy
from typing import Self

from remerkleable.basic import uint64
from remerkleable.byte_arrays import Bytes4
from remerkleable.complex import Container
from remerkleable.core import ObjParseException, ObjType

from spec.common import Root


class Version(Bytes4):
    pass


class Fork(Container):
    previous_version: Version
    current_version: Version
    epoch: uint64


class Genesis(Container):
    genesis_time: uint64
    genesis_validators_root: Root
    genesis_fork_version: Version


class Spec(Container):
    # This value is not used anywhere but
    # the Container subclass creation fails without
    # at least one field
    MIN_GENESIS_TIME: uint64

    @classmethod
    def from_obj(cls, obj: ObjType) -> Self:
        if not isinstance(obj, dict):
            raise ObjParseException(f"obj '{obj}' is not a dict")

        # Create a copy since we manipulate the dict
        _obj = copy.deepcopy(obj)

        fields = cls.fields()
        for k in list(_obj.keys()):
            if k not in fields:
                del _obj[k]  # Remove extra keys/fields

        if any(field not in _obj for field in fields):
            missing = set(fields.keys()) - set(_obj.keys())
            raise ObjParseException(
                f"Required field(s) ({missing}) missing from {_obj}"
            )

        return cls(**{k: fields[k].from_obj(v) for k, v in _obj.items()})


class SpecPhase0(Spec):
    SECONDS_PER_SLOT: uint64
    SLOTS_PER_EPOCH: uint64
    MAX_VALIDATORS_PER_COMMITTEE: uint64
    MAX_COMMITTEES_PER_SLOT: uint64
    GENESIS_FORK_VERSION: Version
    MAX_PROPOSER_SLASHINGS: uint64
    MAX_ATTESTER_SLASHINGS: uint64
    MAX_ATTESTATIONS: uint64
    MAX_DEPOSITS: uint64
    MAX_VOLUNTARY_EXITS: uint64


class SpecAltair(SpecPhase0):
    EPOCHS_PER_SYNC_COMMITTEE_PERIOD: uint64
    SYNC_COMMITTEE_SIZE: uint64
    ALTAIR_FORK_EPOCH: uint64
    ALTAIR_FORK_VERSION: Version


class SpecBellatrix(SpecAltair):
    BELLATRIX_FORK_EPOCH: uint64
    BELLATRIX_FORK_VERSION: Version

    BYTES_PER_LOGS_BLOOM: uint64
    MAX_EXTRA_DATA_BYTES: uint64
    MAX_TRANSACTIONS_PER_PAYLOAD: uint64
    MAX_BYTES_PER_TRANSACTION: uint64


class SpecCapella(SpecBellatrix):
    MAX_WITHDRAWALS_PER_PAYLOAD: uint64
    CAPELLA_FORK_EPOCH: uint64
    CAPELLA_FORK_VERSION: Version
    MAX_BLS_TO_EXECUTION_CHANGES: uint64


class SpecDeneb(SpecCapella):
    MAX_BLOB_COMMITMENTS_PER_BLOCK: uint64
    DENEB_FORK_EPOCH: uint64
    DENEB_FORK_VERSION: Version
    FIELD_ELEMENTS_PER_BLOB: uint64


class SpecElectra(SpecDeneb):
    ELECTRA_FORK_EPOCH: uint64
    ELECTRA_FORK_VERSION: Version
    MAX_DEPOSIT_REQUESTS_PER_PAYLOAD: uint64
    MAX_WITHDRAWAL_REQUESTS_PER_PAYLOAD: uint64
    MAX_CONSOLIDATION_REQUESTS_PER_PAYLOAD: uint64
    MAX_ATTESTATIONS_ELECTRA: uint64
    MAX_ATTESTER_SLASHINGS_ELECTRA: uint64


def parse_spec(data: dict[str, str]) -> SpecElectra:
    return SpecElectra.from_obj(data)
