"""Vero's consensus values, encoded and hashed by Lodestar-Z."""

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from typing import Any, cast

import msgspec
from ssz_z import NativeValue, SSZType, get_type
from ssz_z.beacon_api import BlockValue

from schemas.shared import Fork


@dataclass(frozen=True)
class Checkpoint:
    epoch: int
    root: bytes

    def __repr__(self) -> str:
        return f"Checkpoint(epoch={self.epoch}, root=0x{self.root.hex()})"


class SSZObject:
    """An owned consensus value; every exposed projection is immutable or a copy."""

    def __init__(self, codec: SSZType, value: NativeValue) -> None:
        self._codec = codec
        self._data = value

    @property
    def fork(self) -> Fork:
        return Fork(self._codec.fork)

    @property
    def preset(self) -> str:
        return self._codec.preset

    def to_obj(self) -> dict[str, Any]:
        return cast("dict[str, Any]", msgspec.json.decode(self.to_json()))

    def to_json(self) -> bytes:
        return self._data.to_json()

    def to_ssz(self) -> bytes:
        return self._data.to_ssz()

    def hash_tree_root(self) -> bytes:
        return self._data.hash_tree_root()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SSZObject):
            return NotImplemented
        if self._codec != other._codec:
            return False
        return self.to_ssz() == other.to_ssz()

    def __hash__(self) -> int:
        return hash((self._codec, self.hash_tree_root()))

    def __repr__(self) -> str:
        return f"{self._codec.name}({self._data!r})"


@dataclass(frozen=True)
class SSZCodec[T: SSZObject]:
    codec: SSZType
    value_type: type[T]

    @property
    def preset(self) -> str:
        return self.codec.preset

    def from_json(
        self,
        data: str | bytes | bytearray | memoryview | msgspec.Raw,
        *,
        wrapped: bool = False,
    ) -> T:
        if isinstance(data, msgspec.Raw):
            data = bytes(data)
        if not isinstance(data, (str, bytes, bytearray, memoryview)):
            raise TypeError("Expected JSON text or bytes-like data")
        return self.value_type(self.codec, self.codec.load_json(data, wrapped=wrapped))

    def from_ssz(self, data: bytes) -> T:
        return self.value_type(self.codec, self.codec.load_ssz(data))


def bind_type[T: SSZObject](
    name: str, value_type: type[T], *, fork: Fork, preset: str
) -> SSZCodec[T]:
    return SSZCodec(get_type(name, fork=fork.value, preset=preset), value_type)


def encode_json_array(values: Iterable[SSZObject]) -> bytes:
    return b"[" + b",".join(value.to_json() for value in values) + b"]"


class AttestationData(SSZObject):
    @property
    def slot(self) -> int:
        return cast("int", self._data.field("slot"))

    @property
    def index(self) -> int:
        return cast("int", self._data.field("index"))

    @property
    def beacon_block_root(self) -> bytes:
        return cast("bytes", self._data.field("beacon_block_root"))

    @property
    def source(self) -> Checkpoint:
        return Checkpoint(
            epoch=self._data.field("source.epoch"), root=self._data.field("source.root")
        )

    @property
    def target(self) -> Checkpoint:
        return Checkpoint(
            epoch=self._data.field("target.epoch"), root=self._data.field("target.root")
        )


def _bits(data: bytes, length: int) -> tuple[bool, ...]:
    return tuple(bool(data[index // 8] & (1 << (index % 8))) for index in range(length))


class Attestation(SSZObject):
    @property
    def aggregation_bits(self) -> tuple[bool, ...]:
        data = self._data.field("aggregation_bits")
        # The highest bit is the SSZ bitlist delimiter, including for Gloas.
        return _bits(data, (len(data) - 1) * 8 + data[-1].bit_length() - 1)

    @property
    def committee_bits(self) -> tuple[bool, ...]:
        length = self._codec.schema["fields"]["committee_bits"]["length"]
        return _bits(self._data.field("committee_bits"), length)


class SyncCommitteeContribution(SSZObject):
    @property
    def subcommittee_index(self) -> int:
        return cast("int", self._data.field("subcommittee_index"))

    @property
    def aggregation_bits(self) -> tuple[bool, ...]:
        length = self._codec.schema["fields"]["aggregation_bits"]["length"]
        return _bits(self._data.field("aggregation_bits"), length)


class BeaconBlock(SSZObject):
    @cached_property
    def _block_value(self) -> BlockValue:
        return BlockValue(self._data)

    @property
    def blinded(self) -> bool:
        return self._codec.name == "BlindedBeaconBlock"

    @property
    def slot(self) -> int:
        return self._block_value.slot

    @property
    def builder_index(self) -> int:
        return self._block_value.builder_index

    def header_dict(self) -> dict[str, str]:
        return self._block_value.header_dict()

    def block_hash_tree_root(self) -> str:
        return "0x" + self._block_value.block_hash_tree_root().hex()

    def sign(self, signature: str | bytes) -> SSZObject:
        signed = self._block_value.sign(signature).value
        return SSZObject(signed.codec, signed)


class ExecutionPayloadEnvelope(SSZObject):
    def sign(self, signature: str | bytes) -> SSZObject:
        signed = self._data.sign(signature)
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
