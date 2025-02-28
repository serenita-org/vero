from hashlib import sha256
from typing import Literal

from remerkleable.basic import uint64
from remerkleable.byte_arrays import Bytes32, Bytes48, Bytes96
from remerkleable.core import ObjType

# Some spec values are the same for mainnet, holesky, gnosis, chiado
DEPOSIT_CONTRACT_TREE_DEPTH = uint64(2**5)


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
