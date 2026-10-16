import hashlib
from pathlib import Path
from typing import Any, get_args

import msgspec
import pytest
from ssz_z import SSZError, SSZType, get_type

from spec import Preset
from spec.ssz import (
    Attestation,
    AttestationData,
    BeaconBlock,
    Checkpoint,
    ExecutionPayloadEnvelope,
    Fork,
    SyncCommitteeContribution,
    bind_type,
    encode_json_array,
)
from tests.ssz_objects import bitlist, bitvector

VECTORS = msgspec.json.decode(
    (Path(__file__).parents[1] / "fixtures/ssz/attestations.json").read_bytes()
)["cases"]


@pytest.mark.parametrize("case", VECTORS, ids=lambda c: f"{c['preset']}-{c['fork']}")
def test_official_attestation_vectors(case: dict[str, Any]) -> None:
    codec = bind_type(
        "Attestation", Attestation, fork=Fork(case["fork"]), preset=case["preset"]
    )
    encoded = bytes.fromhex(case["ssz"])
    attestation = codec.from_json(case["value"])
    assert attestation.to_ssz() == encoded
    assert attestation.hash_tree_root().hex() == case["root"][2:]
    assert codec.from_ssz(encoded) == attestation
    assert codec.from_json(attestation.to_json()) == attestation


@pytest.mark.parametrize("fork", list(Fork))
@pytest.mark.parametrize("preset", get_args(Preset))
def test_bitfield_projections(preset: Preset, fork: Fork) -> None:
    codec = bind_type("Attestation", Attestation, fork=fork, preset=preset)
    committee_length = codec.codec.schema["fields"]["committee_bits"]["length"]
    for length in (0, 1, 7, 8, 9, 16):
        value = codec.codec.default()
        value["aggregation_bits"] = bitlist(16, [True] * length)
        value["committee_bits"] = bitvector(committee_length, [True])
        attestation = codec.from_json(value)
        assert len(attestation.aggregation_bits) == length
        assert sum(attestation.aggregation_bits) == length
        assert len(attestation.committee_bits) == committee_length
        assert attestation.committee_bits[0]
        assert sum(attestation.committee_bits) == 1

    sync_codec = bind_type(
        "SyncCommitteeContribution", SyncCommitteeContribution, fork=fork, preset=preset
    )
    value = sync_codec.codec.default()
    length = sync_codec.codec.schema["fields"]["aggregation_bits"]["length"]
    value["aggregation_bits"] = bitvector(length, [True] * length)
    contribution = sync_codec.from_json(value)
    assert len(contribution.aggregation_bits) == length
    assert sum(contribution.aggregation_bits) == length


@pytest.mark.parametrize("fork", list(Fork))
@pytest.mark.parametrize("preset", get_args(Preset))
def test_attestation_values_and_consensus_json(preset: Preset, fork: Fork) -> None:
    codec = bind_type("AttestationData", AttestationData, fork=fork, preset=preset)
    value = codec.codec.default()
    value["slot"] = 2**64 - 1
    value["source"] = {"epoch": 10, "root": b"\x12" * 32}
    data = codec(**value)
    assert data.slot == 2**64 - 1
    assert data.source == Checkpoint(epoch=10, root=b"\x12" * 32)
    assert data.index == 0
    assert data.to_obj()["slot"] == str(2**64 - 1)
    assert data.to_obj()["source"] == {"epoch": "10", "root": "0x" + "12" * 32}
    assert codec.from_ssz(data.to_ssz()) == data
    assert hash(codec.from_ssz(data.to_ssz())) == hash(data)
    assert {data: 1}[codec.from_json(data.to_json())] == 1
    assert msgspec.json.decode(encode_json_array([data, data])) == [data.to_obj()] * 2
    assert encode_json_array([]) == b"[]"
    # Returned JSON values and input dictionaries cannot mutate a cached root.
    root = data.hash_tree_root()
    data.to_obj()["source"]["epoch"] = "123"
    value["source"]["epoch"] = 123
    assert data.source.epoch == 10
    assert data.hash_tree_root() == root
    with pytest.raises(SSZError):
        codec.from_ssz(data.to_ssz()[:-1])
    with pytest.raises(SSZError):
        codec.from_json({**data.to_obj(), "slot": str(2**64)})


def _header_root(header: dict[str, str]) -> str:
    leaves = [
        int(header["slot"]).to_bytes(32, "little"),
        int(header["proposer_index"]).to_bytes(32, "little"),
        *(
            bytes.fromhex(header[name][2:])
            for name in ("parent_root", "state_root", "body_root")
        ),
        *([bytes(32)] * 3),
    ]
    while len(leaves) > 1:
        leaves = [
            hashlib.sha256(leaves[i] + leaves[i + 1]).digest()
            for i in range(0, len(leaves), 2)
        ]
    return "0x" + leaves[0].hex()


@pytest.mark.parametrize(
    ("fork", "name"),
    [
        (Fork.ELECTRA, "BeaconBlockContents"),
        (Fork.ELECTRA, "BlindedBeaconBlock"),
        (Fork.FULU, "BeaconBlockContents"),
        (Fork.FULU, "BlindedBeaconBlock"),
        (Fork.GLOAS, "BeaconBlock"),
    ],
)
@pytest.mark.parametrize("preset", get_args(Preset))
def test_block_signing_and_header_roots(preset: Preset, fork: Fork, name: str) -> None:
    codec = bind_type(name, BeaconBlock, fork=fork, preset=preset)
    value = codec.codec.default()
    block_value = value["block"] if name == "BeaconBlockContents" else value
    block_value.update(slot=123, proposer_index=456, parent_root=b"\x12" * 32)
    if name == "BeaconBlockContents":
        body = block_value["body"]
        body["execution_payload"]["transactions"] = [b"\x01\x02\x03"]
        body["blob_kzg_commitments"] = [b"\x34" * 48]
        value["blobs"] = [get_type("Blob", fork=fork, preset=preset).default()]
        value["kzg_proofs"] = [b"\x56" * 48] * (128 if fork is Fork.FULU else 1)
    block = codec.from_json(value)
    assert block.slot == 123
    assert block.blinded == (name == "BlindedBeaconBlock")
    assert block.block_hash_tree_root() == _header_root(block.header_dict())
    assert codec.from_ssz(block.to_ssz()).header_dict() == block.header_dict()
    signature = b"\x78" * 96
    signed = block.sign(signature)
    signed_codec = get_type("Signed" + name, fork=fork, preset=preset)
    restored = signed_codec.deserialize(signed.to_ssz())
    signed_block = (
        restored["signed_block"] if name == "BeaconBlockContents" else restored
    )
    assert signed_block["message"] == block_value
    assert signed_block["signature"] == signature
    if name == "BeaconBlockContents":
        assert restored["blobs"] == value["blobs"]
        assert restored["kzg_proofs"] == value["kzg_proofs"]
        assert block.block_hash_tree_root() != "0x" + block.hash_tree_root().hex()
    assert signed_codec.from_json(signed.to_json()) == restored
    assert codec.from_json(block.to_json()) == block
    with pytest.raises(SSZError):
        block.sign(b"\x00" * 95)


@pytest.mark.parametrize("preset", get_args(Preset))
def test_execution_payload_envelope_signing(preset: Preset) -> None:
    codec = bind_type(
        "ExecutionPayloadEnvelope",
        ExecutionPayloadEnvelope,
        fork=Fork.GLOAS,
        preset=preset,
    )
    value = codec.codec.default()
    value["payload"]["transactions"] = [b"\x01\x02\x03"]
    value["builder_index"] = 2**64 - 1
    envelope = codec.from_json(value)
    assert codec.from_ssz(envelope.to_ssz()) == envelope
    signed = envelope.sign("0x" + "34" * 96)
    signed_codec = get_type(
        "SignedExecutionPayloadEnvelope", fork="gloas", preset=preset
    )
    restored = signed_codec.deserialize(signed.to_ssz())
    assert restored == {"message": value, "signature": b"\x34" * 96}
    assert signed_codec.from_json(signed.to_json()) == restored


@pytest.mark.parametrize(
    ("fork", "name"),
    [
        (Fork.ELECTRA, "BeaconBlockContents"),
        (Fork.ELECTRA, "BlindedBeaconBlock"),
        (Fork.FULU, "BeaconBlockContents"),
        (Fork.FULU, "BlindedBeaconBlock"),
        (Fork.GLOAS, "BeaconBlock"),
    ],
)
def test_proposal_path_avoids_python_value_conversion(
    fork: Fork, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    codec = bind_type(name, BeaconBlock, fork=fork, preset="minimal")
    value = codec.codec.default()
    block = value["block"] if name == "BeaconBlockContents" else value
    block["slot"] = 123
    if fork is Fork.GLOAS:
        block["body"]["signed_execution_payload_bid"]["message"]["builder_index"] = 456
    encoded_ssz = codec.codec.serialize(value)
    encoded_json = msgspec.json.encode(
        {"version": fork.value, "data": codec.codec.to_json(value)}
    )

    def materialize(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Proposal processing used the dictionary conversion API")

    with monkeypatch.context() as patch:
        for method in ("serialize", "deserialize", "from_json", "to_json"):
            patch.setattr(SSZType, method, materialize)
        from_ssz = codec.from_ssz(encoded_ssz)
        from_json = codec.from_json(encoded_json, wrapped=True)
        assert from_ssz == from_json
        assert from_ssz.to_ssz() is encoded_ssz
        assert from_ssz.slot == 123
        if fork is Fork.GLOAS:
            assert from_ssz.builder_index == 456
        header = from_ssz.header_dict()
        assert from_ssz.block_hash_tree_root() == _header_root(header)
        assert from_ssz.block_hash_tree_root() == from_json.block_hash_tree_root()
        signed_ssz = from_ssz.sign(bytes(96)).to_ssz()
        signed_json = from_json.sign(bytes(96)).to_json()
    signed_codec = get_type("Signed" + name, fork=fork, preset="minimal")
    assert signed_codec.from_json(signed_json) == signed_codec.deserialize(signed_ssz)
