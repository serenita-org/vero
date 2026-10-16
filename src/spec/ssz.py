"""Vero's consensus values, encoded and hashed by Lodestar-Z."""

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from typing import Any, cast

import msgspec
from ssz_z import NativeValue, SSZType, get_type


class Fork(StrEnum):
    ELECTRA = "electra"
    FULU = "fulu"
    GLOAS = "gloas"


@dataclass(frozen=True)
class Checkpoint:
    epoch: int
    root: bytes

    def __repr__(self) -> str:
        return f"Checkpoint(epoch={self.epoch}, root=0x{self.root.hex()})"


def _value(value: Any) -> Any:
    if isinstance(value, SSZObject):
        return value._value  # noqa: SLF001 - unwrap our own value objects
    if isinstance(value, Checkpoint):
        return {"epoch": value.epoch, "root": value.root}
    if isinstance(value, dict):
        return {key: _value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_value(item) for item in value]
    return value


class SSZObject:
    """An owned consensus value; every exposed projection is immutable or a copy."""

    def __init__(self, codec: SSZType, value: dict[str, Any] | NativeValue) -> None:
        self._codec = codec
        self._data = value

    @cached_property
    def _value(self) -> dict[str, Any]:
        if isinstance(self._data, NativeValue):
            return cast("dict[str, Any]", self._data.to_obj())
        return self._data

    @property
    def fork(self) -> Fork:
        return Fork(self._codec.fork)

    @property
    def preset(self) -> str:
        return self._codec.preset

    def to_obj(self) -> dict[str, Any]:
        return cast("dict[str, Any]", self._codec.to_json(self._data))

    def to_json(self) -> bytes:
        if isinstance(self._data, NativeValue):
            return self._data.to_json()
        return msgspec.json.encode(self.to_obj())

    @cached_property
    def _serialized(self) -> bytes:
        if isinstance(self._data, NativeValue):
            return self._data.to_ssz()
        return self._codec.serialize(self._data)

    def to_ssz(self) -> bytes:
        return self._serialized

    @cached_property
    def _root(self) -> bytes:
        if isinstance(self._data, NativeValue):
            return self._data.hash_tree_root()
        return self._codec.hash_tree_root_from_ssz(self._serialized)

    def hash_tree_root(self) -> bytes:
        return self._root

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SSZObject):
            return NotImplemented
        if self._codec != other._codec:
            return False
        if isinstance(self._data, dict) and isinstance(other._data, dict):
            return self._data == other._data
        return self.to_ssz() == other.to_ssz()

    def __hash__(self) -> int:
        return hash((self._codec, self._root))

    def __repr__(self) -> str:
        return f"{self._codec.name}({self._data!r})"


class NativeSSZObject(SSZObject):
    """Keep large consensus values in SSZ form throughout the proposal path."""

    @property
    def _native_value(self) -> NativeValue:
        if not isinstance(self._data, NativeValue):
            raise TypeError("Expected an SSZ-backed value")
        return self._data


@dataclass(frozen=True)
class SSZCodec[T: SSZObject]:
    codec: SSZType
    value_type: type[T]

    @property
    def preset(self) -> str:
        return self.codec.preset

    def __call__(self, **fields: Any) -> T:
        return self.from_json(_value(fields))

    def from_json(self, data: Any, *, wrapped: bool = False) -> T:
        if isinstance(data, msgspec.Raw):
            data = bytes(data)
        if issubclass(self.value_type, NativeSSZObject):
            value = (
                self.codec.load_json(data, wrapped=wrapped)
                if isinstance(data, (str, bytes, bytearray, memoryview))
                else self.codec.load_obj(data)
            )
            return self.value_type(self.codec, value)
        if wrapped:
            raise TypeError("Wrapped JSON is only supported for native values")
        return self.value_type(self.codec, self.codec.from_json(data))

    def from_ssz(self, data: bytes) -> T:
        if issubclass(self.value_type, NativeSSZObject):
            return self.value_type(self.codec, self.codec.load_ssz(data))
        value = self.value_type(self.codec, self.codec.deserialize(data))
        value.__dict__["_serialized"] = bytes(data)
        return value


def bind_type[T: SSZObject](
    name: str, value_type: type[T], *, fork: Fork, preset: str
) -> SSZCodec[T]:
    return SSZCodec(get_type(name, fork=fork.value, preset=preset), value_type)


def encode_json_array(values: Iterable[SSZObject]) -> bytes:
    return b"[" + b",".join(value.to_json() for value in values) + b"]"


class AttestationData(SSZObject):
    @property
    def slot(self) -> int:
        return cast("int", self._value["slot"])

    @property
    def index(self) -> int:
        return cast("int", self._value["index"])

    @property
    def beacon_block_root(self) -> bytes:
        return cast("bytes", self._value["beacon_block_root"])

    @property
    def source(self) -> Checkpoint:
        return Checkpoint(**self._value["source"])

    @property
    def target(self) -> Checkpoint:
        return Checkpoint(**self._value["target"])


def _bits(data: bytes, length: int) -> tuple[bool, ...]:
    return tuple(bool(data[index // 8] & (1 << (index % 8))) for index in range(length))


class Attestation(SSZObject):
    @property
    def aggregation_bits(self) -> tuple[bool, ...]:
        data = self._value["aggregation_bits"]
        # The highest bit is the SSZ bitlist delimiter, including for Gloas.
        return _bits(data, (len(data) - 1) * 8 + data[-1].bit_length() - 1)

    @property
    def committee_bits(self) -> tuple[bool, ...]:
        length = self._codec.schema["fields"]["committee_bits"]["length"]
        return _bits(self._value["committee_bits"], length)


class SyncCommitteeContribution(SSZObject):
    @property
    def subcommittee_index(self) -> int:
        return cast("int", self._value["subcommittee_index"])

    @property
    def aggregation_bits(self) -> tuple[bool, ...]:
        length = self._codec.schema["fields"]["aggregation_bits"]["length"]
        return _bits(self._value["aggregation_bits"], length)


class BeaconBlock(NativeSSZObject):
    @property
    def blinded(self) -> bool:
        return self._codec.name == "BlindedBeaconBlock"

    @property
    def slot(self) -> int:
        return self._native_value.slot

    @property
    def builder_index(self) -> int:
        return self._native_value.builder_index

    def header_dict(self) -> dict[str, str]:
        return self._native_value.header_dict()

    def block_hash_tree_root(self) -> str:
        return "0x" + self._native_value.block_hash_tree_root().hex()

    def sign(self, signature: str | bytes) -> SSZObject:
        signed = self._native_value.sign(signature)
        return SSZObject(signed.codec, signed)


class ExecutionPayloadEnvelope(NativeSSZObject):
    def sign(self, signature: str | bytes) -> SSZObject:
        signed = self._native_value.sign(signature)
        return SSZObject(signed.codec, signed)


# These outbound containers need no field projections in Vero.
AggregateAndProof = SSZObject
ContributionAndProof = SSZObject
PayloadAttestationData = SSZObject
PayloadAttestationMessage = SSZObject
SignedAggregateAndProof = SSZObject
SignedBeaconBlock = SSZObject
SignedContributionAndProof = SSZObject
SingleAttestation = SSZObject
SyncCommitteeMessage = SSZObject
