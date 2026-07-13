from hashlib import sha256
from typing import Any, Literal, Self


class Uint64(int):
    def __new__(cls, value: int | str = 0) -> Self:
        parsed = int(value)
        if not 0 <= parsed < 2**64:
            raise ValueError(f"uint64 value out of range: {parsed}")
        return int.__new__(cls, parsed)

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


def bytes_to_uint64(
    data: bytes,
    _endianness: Literal["little", "big"] = "little",
) -> Uint64:
    return Uint64(int.from_bytes(data, _endianness))


def hash_function(x: bytes | bytearray | memoryview) -> Bytes32:
    return Bytes32(sha256(x).digest())


class UInt64SerializedAsString(Uint64):
    pass


class Root(Bytes32):
    pass


def to_obj(value: Any) -> Any:
    if hasattr(value, "to_obj"):
        return value.to_obj()
    if isinstance(value, dict):
        return {key: to_obj(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_obj(item) for item in value]
    return value
