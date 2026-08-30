from hashlib import sha256
from typing import Self


class Uint64(int):
    def __new__(cls, value: int | str = 0) -> Self:
        parsed = int(value)
        if not 0 <= parsed < 2**64:
            raise ValueError(f"uint64 value out of range: {parsed}")
        return int.__new__(cls, parsed)

    @classmethod
    def from_obj(cls, value: str) -> Self:
        if not isinstance(value, str):
            raise TypeError(
                f"uint64 JSON value must be a string, got {type(value).__name__}"
            )
        return cls(value)

    def to_obj(self) -> str:
        return str(self)


class FixedBytes(bytes):
    length: int

    def __new__(cls, value: bytes | bytearray | memoryview | str | None = None) -> Self:
        if value is None:
            raw = bytes(cls.length)
        elif isinstance(value, str):
            raw = bytes.fromhex(value.removeprefix("0x"))
        else:
            raw = bytes(value)
        if len(raw) != cls.length:
            raise ValueError(
                f"{cls.__name__} requires {cls.length} bytes, got {len(raw)}"
            )
        return bytes.__new__(cls, raw)

    def to_obj(self) -> str:
        return f"0x{self.hex()}"


class Bytes4(FixedBytes):
    length = 4


class Bytes32(FixedBytes):
    length = 32

from spec.constants import BASIS_POINTS


def bytes_to_uint64(
    data: bytes,
) -> Uint64:
    return Uint64(int.from_bytes(data, byteorder="little"))


def hash_function(x: bytes | bytearray | memoryview) -> Bytes32:
    return Bytes32(sha256(x).digest())

def get_slot_component_duration_ms(
    basis_points: Uint64, slot_duration_ms: Uint64
) -> int:
    """
    Calculate the duration of a slot component in milliseconds.
    """
    return int(basis_points * slot_duration_ms // BASIS_POINTS)


class Root(Bytes32):
    pass
