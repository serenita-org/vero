from hashlib import sha256
from typing import Literal

from remerkleable.basic import uint64, uint256
from remerkleable.byte_arrays import Bytes32, Bytes48, Bytes96
from remerkleable.core import ObjType

from spec.constants import BASIS_POINTS


def bytes_to_uint64(
    data: bytes,
    _endianness: Literal["little", "big"] = "little",
) -> uint64:
    """Return the integer deserialization of ``data`` interpreted as ``ENDIANNESS``-endian."""
    return uint64(int.from_bytes(data, _endianness))


def hash_function(x: bytes | bytearray | memoryview) -> Bytes32:
    return Bytes32(sha256(x).digest())


class BLSSignature(Bytes96):
    pass


class UInt64SerializedAsString(uint64):
    def to_obj(self) -> ObjType:
        return str(self)


def get_slot_component_duration_ms(
    basis_points: UInt64SerializedAsString, slot_duration_ms: UInt64SerializedAsString
) -> int:
    """
    Calculate the duration of a slot component in milliseconds.
    """
    return int(basis_points * slot_duration_ms // BASIS_POINTS)


class UInt256SerializedAsString(uint256):
    def to_obj(self) -> ObjType:
        return str(self)


class Slot(UInt64SerializedAsString):
    pass


class Epoch(UInt64SerializedAsString):
    pass


class Root(Bytes32):
    pass


class Hash32(Bytes32):
    pass


class BLSPubkey(Bytes48):
    pass


class ValidatorIndex(UInt64SerializedAsString):
    pass
