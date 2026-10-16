from collections.abc import Iterable
from typing import Any

import msgspec
from ssz_z import get_type

from spec import (
    Attestation,
    AttestationData,
    BeaconBlock,
    SyncCommitteeContribution,
    preset_types,
)
from spec.constants import SYNC_COMMITTEE_SUBNET_COUNT
from spec.ssz import ExecutionPayloadEnvelope, Fork, SSZCodec, bind_type

BYTES_PER_BLS_SIGNATURE = 96
BYTES_PER_EXECUTION_ADDRESS = 20
BYTES_PER_LOGS_BLOOM = 256
BYTES_PER_ROOT = 32

ZERO_ROOT = "0x" + "00" * BYTES_PER_ROOT
ZERO_SIGNATURE = "0x" + "00" * BYTES_PER_BLS_SIGNATURE


def attestation_data_obj(**overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "slot": "0",
        "index": "0",
        "beacon_block_root": ZERO_ROOT,
        "source": {"epoch": "0", "root": ZERO_ROOT},
        "target": {"epoch": "0", "root": ZERO_ROOT},
    }
    value.update(overrides)
    return value


def make_attestation_data(**overrides: Any) -> AttestationData:
    attestation_data_type: SSZCodec[AttestationData] = preset_types().attestation_data
    return attestation_data_type.from_json(
        msgspec.json.encode(attestation_data_obj(**overrides))
    )


def make_attestation(**overrides: Any) -> Attestation:
    attestation_type: SSZCodec[Attestation] = preset_types().attestation
    preset_config = preset_constants()
    value: dict[str, Any] = {
        "aggregation_bits": "0x01",
        "data": attestation_data_obj(),
        "signature": ZERO_SIGNATURE,
        "committee_bits": bitvector(preset_config["max_committees_per_slot"]),
    }
    value.update(overrides)
    if isinstance(value["data"], AttestationData):
        value["data"] = msgspec.Raw(value["data"].to_json())
    return attestation_type.from_json(msgspec.json.encode(value))


def make_contribution(**overrides: Any) -> SyncCommitteeContribution:
    contribution_type: SSZCodec[SyncCommitteeContribution] = (
        preset_types().sync_committee_contribution
    )
    preset_config = preset_constants()
    value: dict[str, Any] = {
        "slot": "0",
        "beacon_block_root": ZERO_ROOT,
        "subcommittee_index": "0",
        "aggregation_bits": bitvector(
            preset_config["sync_committee_size"] // SYNC_COMMITTEE_SUBNET_COUNT
        ),
        "signature": ZERO_SIGNATURE,
    }
    value.update(overrides)
    return contribution_type.from_json(msgspec.json.encode(value))


def _block_body_electra_fulu(*, blinded: bool) -> dict[str, Any]:
    preset_config = preset_constants()
    execution_common = {
        "parent_hash": ZERO_ROOT,
        "fee_recipient": "0x" + "00" * BYTES_PER_EXECUTION_ADDRESS,
        "state_root": ZERO_ROOT,
        "receipts_root": ZERO_ROOT,
        "logs_bloom": "0x" + "00" * BYTES_PER_LOGS_BLOOM,
        "prev_randao": ZERO_ROOT,
        "block_number": "0",
        "gas_limit": "0",
        "gas_used": "0",
        "timestamp": "0",
        "extra_data": "0x",
        "base_fee_per_gas": "0",
        "block_hash": ZERO_ROOT,
        "blob_gas_used": "0",
        "excess_blob_gas": "0",
    }
    execution = (
        {
            **execution_common,
            "transactions_root": ZERO_ROOT,
            "withdrawals_root": ZERO_ROOT,
        }
        if blinded
        else {**execution_common, "transactions": [], "withdrawals": []}
    )
    return {
        "randao_reveal": ZERO_SIGNATURE,
        "eth1_data": {
            "deposit_root": ZERO_ROOT,
            "deposit_count": "0",
            "block_hash": ZERO_ROOT,
        },
        "graffiti": ZERO_ROOT,
        "proposer_slashings": [],
        "attester_slashings": [],
        "attestations": [],
        "deposits": [],
        "voluntary_exits": [],
        "sync_aggregate": {
            "sync_committee_bits": bitvector(preset_config["sync_committee_size"]),
            "sync_committee_signature": ZERO_SIGNATURE,
        },
        "execution_payload_header" if blinded else "execution_payload": execution,
        "bls_to_execution_changes": [],
        "blob_kzg_commitments": [],
        "execution_requests": {"deposits": [], "withdrawals": [], "consolidations": []},
    }


def make_block_electra_fulu(*, slot: int, blinded: bool) -> BeaconBlock:
    block_types = preset_types()
    block = {
        "slot": str(slot),
        "proposer_index": "123",
        "parent_root": "0xcbe950dda3533e3c257fd162b33d791f9073eb42e4da21def569451e9323c33e",
        "state_root": "0xd9f5a83718a7657f50bc3c5be8c2b2fd7f051f44d2962efdde1e30cee881e7f6",
        "body": _block_body_electra_fulu(blinded=blinded),
    }
    block_type = bind_type(
        "BlindedBeaconBlock" if blinded else "BeaconBlockContents",
        BeaconBlock,
        fork=Fork.FULU,
        preset=block_types.preset,
    )
    if blinded:
        return block_type.from_json(block)
    return block_type.from_json({"block": block, "kzg_proofs": [], "blobs": []})


def _block_body_gloas(*, builder_index: int) -> dict[str, Any]:
    preset_config = preset_constants()
    return {
        "randao_reveal": ZERO_SIGNATURE,
        "eth1_data": {
            "deposit_root": ZERO_ROOT,
            "deposit_count": "0",
            "block_hash": ZERO_ROOT,
        },
        "graffiti": ZERO_ROOT,
        "proposer_slashings": [],
        "attester_slashings": [],
        "attestations": [],
        "deposits": [],
        "voluntary_exits": [],
        "sync_aggregate": {
            "sync_committee_bits": bitvector(preset_config["sync_committee_size"]),
            "sync_committee_signature": ZERO_SIGNATURE,
        },
        "bls_to_execution_changes": [],
        "signed_execution_payload_bid": {
            "message": {
                "parent_block_hash": ZERO_ROOT,
                "parent_block_root": ZERO_ROOT,
                "block_hash": ZERO_ROOT,
                "prev_randao": ZERO_ROOT,
                "fee_recipient": "0x" + "00" * BYTES_PER_EXECUTION_ADDRESS,
                "gas_limit": "0",
                "builder_index": str(builder_index),
                "slot": "1234",
                "value": "54321",
                "execution_payment": "0",
                "blob_kzg_commitments": [],
                "execution_requests_root": ZERO_ROOT,
            },
            "signature": ZERO_SIGNATURE,
        },
        "payload_attestations": [],
        "parent_execution_requests": {
            "deposits": [],
            "withdrawals": [],
            "consolidations": [],
            "builder_deposits": [],
            "builder_exits": [],
        },
    }


def make_block_gloas(*, slot: int, builder_index: int) -> BeaconBlock:
    block = {
        "slot": str(slot),
        "proposer_index": "123",
        "parent_root": "0xcbe950dda3533e3c257fd162b33d791f9073eb42e4da21def569451e9323c33e",
        "state_root": "0xd9f5a83718a7657f50bc3c5be8c2b2fd7f051f44d2962efdde1e30cee881e7f6",
        "body": _block_body_gloas(builder_index=builder_index),
    }
    block_type = bind_type(
        "BeaconBlock", BeaconBlock, fork=Fork.GLOAS, preset=preset_types().preset
    )
    return block_type.from_json(block)


def make_execution_payload_envelope_gloas(
    *, beacon_block_root: str = ZERO_ROOT
) -> ExecutionPayloadEnvelope:
    envelope_type = bind_type(
        "ExecutionPayloadEnvelope",
        ExecutionPayloadEnvelope,
        fork=Fork.GLOAS,
        preset=preset_types().preset,
    )
    envelope = {
        "payload": {
            "parent_hash": ZERO_ROOT,
            "fee_recipient": "0x" + "00" * BYTES_PER_EXECUTION_ADDRESS,
            "state_root": ZERO_ROOT,
            "receipts_root": ZERO_ROOT,
            "logs_bloom": "0x" + "00" * BYTES_PER_LOGS_BLOOM,
            "prev_randao": ZERO_ROOT,
            "block_number": "0",
            "gas_limit": "0",
            "gas_used": "0",
            "timestamp": "0",
            "extra_data": "0x",
            "base_fee_per_gas": "0",
            "block_hash": ZERO_ROOT,
            "transactions": [],
            "withdrawals": [],
            "blob_gas_used": "0",
            "excess_blob_gas": "0",
            "block_access_list": "0x",
            "slot_number": "0",
        },
        "execution_requests": {
            "deposits": [],
            "withdrawals": [],
            "consolidations": [],
            "builder_deposits": [],
            "builder_exits": [],
        },
        "builder_index": "0",
        "beacon_block_root": beacon_block_root,
        "parent_beacon_block_root": ZERO_ROOT,
    }
    return envelope_type.from_json(envelope)


def preset_constants() -> dict[str, int]:
    codec = get_type("Attestation", fork="fulu", preset=preset_types().preset)
    sync = get_type("SyncAggregate", fork="fulu", preset=preset_types().preset)
    return {
        "max_committees_per_slot": codec.schema["fields"]["committee_bits"]["length"],
        "sync_committee_size": sync.schema["fields"]["sync_committee_bits"]["length"],
    }


def bitvector(length: int, values: Iterable[bool | int] = ()) -> str:
    bits = list(values)
    if len(bits) > length:
        raise ValueError("too many bits")
    data = bytearray((length + 7) // 8)
    for index, bit in enumerate(bits):
        if bit:
            data[index // 8] |= 1 << (index % 8)
    return "0x" + data.hex()


def bitlist(limit: int, values: Iterable[bool | int] = ()) -> str:
    bits = list(values)
    if len(bits) > limit:
        raise ValueError("too many bits")
    return bitvector(len(bits) + 1, [*bits, True])
