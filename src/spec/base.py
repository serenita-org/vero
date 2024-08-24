import logging
from typing import Type

from remerkleable.basic import uint64
from remerkleable.byte_arrays import Bytes4
from remerkleable.complex import Container, CV
from remerkleable.core import ObjType, ObjParseException

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
    def from_obj(cls: Type[CV], obj: ObjType) -> CV:
        if not isinstance(obj, dict):
            raise ObjParseException(f"obj '{obj}' is not a dict")
        fields = cls.fields()
        for k in list(obj.keys()):
            if k not in fields:
                del obj[k]  # Remove extra keys/fields

        # Handle missing value for INTERVALS_PER_SLOT from some CL clients
        # TODO report and get rid of this workaround?
        logger = logging.getLogger("spec-parser")
        if "INTERVALS_PER_SLOT" not in obj:
            logger.warning(
                "Missing spec value for INTERVALS_PER_SLOT, using default of 3"
            )
            obj["INTERVALS_PER_SLOT"] = 3

        # Handle missing value for MAX_BLOB_COMMITMENTS_PER_BLOCK from Prysm
        # TODO report and get rid of this workaround?
        if "MAX_BLOB_COMMITMENTS_PER_BLOCK" not in obj:
            logger.warning(
                "Missing spec value for MAX_BLOB_COMMITMENTS_PER_BLOCK, using default of 4096"
            )
            obj["MAX_BLOB_COMMITMENTS_PER_BLOCK"] = 4096

        if any(field not in obj for field in fields):
            missing = set(fields.keys()) - set(obj.keys())
            raise ObjParseException(
                f"obj '{obj}' is missing required field(s): {missing}"
            )

        return cls(**{k: fields[k].from_obj(v) for k, v in obj.items()})  # type: ignore


class SpecPhase0(Spec):
    INTERVALS_PER_SLOT: uint64
    SECONDS_PER_SLOT: uint64
    SLOTS_PER_EPOCH: uint64
    TARGET_AGGREGATORS_PER_COMMITTEE: uint64
    MAX_VALIDATORS_PER_COMMITTEE: uint64
    GENESIS_FORK_VERSION: Version


class SpecAltair(SpecPhase0):
    EPOCHS_PER_SYNC_COMMITTEE_PERIOD: uint64
    SYNC_COMMITTEE_SIZE: uint64
    SYNC_COMMITTEE_SUBNET_COUNT: uint64
    TARGET_AGGREGATORS_PER_SYNC_SUBCOMMITTEE: uint64
    ALTAIR_FORK_EPOCH: uint64
    ALTAIR_FORK_VERSION: Version


class SpecBellatrix(SpecAltair):
    MAX_WITHDRAWALS_PER_PAYLOAD: uint64
    BELLATRIX_FORK_EPOCH: uint64
    BELLATRIX_FORK_VERSION: Version


class SpecCapella(SpecBellatrix):
    MAX_WITHDRAWALS_PER_PAYLOAD: uint64
    CAPELLA_FORK_EPOCH: uint64
    CAPELLA_FORK_VERSION: Version


class SpecDeneb(SpecCapella):
    MAX_BLOB_COMMITMENTS_PER_BLOCK: uint64
    DENEB_FORK_EPOCH: uint64
    DENEB_FORK_VERSION: Version


class SpecElectra(SpecDeneb):
    ELECTRA_FORK_EPOCH: uint64
    ELECTRA_FORK_VERSION: Version


def parse_spec(data: dict) -> Spec:
    # TODO add SpecElectra once all CLs return it
    #  not added yet because right now this causes
    #  MultiBeaconNode to fail if there is a spec
    #  mismatch. We could also disable/remove that
    #  spec match check though?
    _specs_descending_order = [
        SpecDeneb,
        SpecCapella,
        SpecBellatrix,
        SpecAltair,
        SpecPhase0,
    ]
    for spec in _specs_descending_order:
        try:
            return spec.from_obj(data)
        except ObjParseException:
            pass
    raise ValueError(f"Failed to parse spec from data: {data}")
