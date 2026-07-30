from typing import Any, cast

import msgspec
from spy_ssz import (
    Bitfield,
    Fork,
    ObjectKind,
    Preset,
    get_ssz_type,
    load_preset,
)

from spec import (
    Attestation,
    AttestationData,
    BeaconBlock,
    SyncCommitteeContribution,
    preset_types,
)
from spec.constants import SYNC_COMMITTEE_SUBNET_COUNT

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
    attestation_data_type: type[AttestationData] = preset_types().attestation_data
    return attestation_data_type.from_json(
        msgspec.json.encode(attestation_data_obj(**overrides))
    )


def make_attestation(**overrides: Any) -> Attestation:
    attestation_type: type[Attestation] = preset_types().attestation
    preset_config = load_preset(attestation_type.expected_preset)
    value: dict[str, Any] = {
        "aggregation_bits": "0x01",
        "data": attestation_data_obj(),
        "signature": ZERO_SIGNATURE,
        "committee_bits": Bitfield.bitvector(
            preset_config.max_committees_per_slot
        ).to_hex(),
    }
    value.update(overrides)
    for field in ("aggregation_bits", "committee_bits"):
        if isinstance(value[field], Bitfield):
            value[field] = value[field].to_hex()
    if isinstance(value["data"], AttestationData):
        value["data"] = msgspec.Raw(value["data"].to_json())
    return attestation_type.from_json(msgspec.json.encode(value))


def make_contribution(**overrides: Any) -> SyncCommitteeContribution:
    contribution_type: type[SyncCommitteeContribution] = (
        preset_types().sync_committee_contribution
    )
    preset_config = load_preset(contribution_type.expected_preset)
    value: dict[str, Any] = {
        "slot": "0",
        "beacon_block_root": ZERO_ROOT,
        "subcommittee_index": "0",
        "aggregation_bits": Bitfield.bitvector(
            preset_config.sync_committee_size // SYNC_COMMITTEE_SUBNET_COUNT
        ).to_hex(),
        "signature": ZERO_SIGNATURE,
    }
    value.update(overrides)
    if isinstance(value["aggregation_bits"], Bitfield):
        value["aggregation_bits"] = value["aggregation_bits"].to_hex()
    return contribution_type.from_json(msgspec.json.encode(value))


def _block_body(*, blinded: bool) -> dict[str, Any]:
    preset_config = load_preset(Preset[preset_types().preset.upper()])
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
            "sync_committee_bits": Bitfield.bitvector(
                preset_config.sync_committee_size
            ).to_hex(),
            "sync_committee_signature": ZERO_SIGNATURE,
        },
        "execution_payload_header" if blinded else "execution_payload": execution,
        "bls_to_execution_changes": [],
        "blob_kzg_commitments": [],
        "execution_requests": {"deposits": [], "withdrawals": [], "consolidations": []},
    }


def make_block(*, slot: int, blinded: bool) -> BeaconBlock:
    block_types = preset_types()
    block = {
        "slot": str(slot),
        "proposer_index": "123",
        "parent_root": "0xcbe950dda3533e3c257fd162b33d791f9073eb42e4da21def569451e9323c33e",
        "state_root": "0xd9f5a83718a7657f50bc3c5be8c2b2fd7f051f44d2962efdde1e30cee881e7f6",
        "body": _block_body(blinded=blinded),
    }
    block_type = get_ssz_type(
        Fork.FULU,
        ObjectKind.BLINDED_BEACON_BLOCK
        if blinded
        else ObjectKind.BEACON_BLOCK_CONTENTS,
        Preset[block_types.preset.upper()],
    )
    if blinded:
        return cast(
            "BeaconBlock",
            block_type.from_json(msgspec.json.encode({"data": block})),
        )
    return cast(
        "BeaconBlock",
        block_type.from_json(
            msgspec.json.encode(
                {"data": {"block": block, "kzg_proofs": [], "blobs": []}}
            )
        ),
    )
