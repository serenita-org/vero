from dataclasses import dataclass
from typing import Literal

from .ssz import (
    AggregateAndProof as AggregateAndProof,
    Attestation as Attestation,
    AttestationData as AttestationData,
    BeaconBlock as BeaconBlock,
    Checkpoint as Checkpoint,
    ContributionAndProof as ContributionAndProof,
    Fork,
    PayloadAttestationData as PayloadAttestationData,
    PayloadAttestationMessage as PayloadAttestationMessage,
    SignedAggregateAndProof as SignedAggregateAndProof,
    SignedBeaconBlock as SignedBeaconBlock,
    SignedContributionAndProof as SignedContributionAndProof,
    SingleAttestation as SingleAttestation,
    SSZCodec,
    SyncCommitteeContribution as SyncCommitteeContribution,
    SyncCommitteeMessage as SyncCommitteeMessage,
    bind_type,
)

Preset = Literal["mainnet", "minimal", "gnosis"]


@dataclass(frozen=True)
class PresetTypes:
    preset: Preset
    fork: Fork
    attestation_data: SSZCodec[AttestationData]
    attestation: SSZCodec[Attestation]
    aggregate_and_proof: SSZCodec[AggregateAndProof]
    sync_committee_contribution: SSZCodec[SyncCommitteeContribution]
    contribution_and_proof: SSZCodec[ContributionAndProof]
    payload_attestation_data: SSZCodec[PayloadAttestationData]
    payload_attestation_message: SSZCodec[PayloadAttestationMessage]
    single_attestation: SSZCodec[SingleAttestation]
    sync_committee_message: SSZCodec[SyncCommitteeMessage]
    signed_aggregate_and_proof: SSZCodec[SignedAggregateAndProof]
    signed_contribution_and_proof: SSZCodec[SignedContributionAndProof]


_active_types: dict[Fork, PresetTypes] = {}


def _initialize_fork_types(preset: Preset, fork: Fork) -> PresetTypes:
    return PresetTypes(
        preset=preset,
        fork=fork,
        attestation_data=bind_type(
            "AttestationData", AttestationData, fork=fork, preset=preset
        ),
        attestation=bind_type("Attestation", Attestation, fork=fork, preset=preset),
        aggregate_and_proof=bind_type(
            "AggregateAndProof", AggregateAndProof, fork=fork, preset=preset
        ),
        sync_committee_contribution=bind_type(
            "SyncCommitteeContribution",
            SyncCommitteeContribution,
            fork=fork,
            preset=preset,
        ),
        contribution_and_proof=bind_type(
            "ContributionAndProof", ContributionAndProof, fork=fork, preset=preset
        ),
        payload_attestation_data=bind_type(
            "PayloadAttestationData",
            PayloadAttestationData,
            fork=Fork.GLOAS,
            preset=preset,
        ),
        payload_attestation_message=bind_type(
            "PayloadAttestationMessage",
            PayloadAttestationMessage,
            fork=Fork.GLOAS,
            preset=preset,
        ),
        single_attestation=bind_type(
            "SingleAttestation", SingleAttestation, fork=fork, preset=preset
        ),
        sync_committee_message=bind_type(
            "SyncCommitteeMessage", SyncCommitteeMessage, fork=fork, preset=preset
        ),
        signed_aggregate_and_proof=bind_type(
            "SignedAggregateAndProof", SignedAggregateAndProof, fork=fork, preset=preset
        ),
        signed_contribution_and_proof=bind_type(
            "SignedContributionAndProof",
            SignedContributionAndProof,
            fork=fork,
            preset=preset,
        ),
    )


def initialize_preset(preset: Preset) -> None:
    global _active_types
    _active_types = {fork: _initialize_fork_types(preset, fork) for fork in Fork}


def preset_types(fork: Fork = Fork.FULU) -> PresetTypes:
    if not _active_types:
        raise RuntimeError("initialize_preset was not called")
    return _active_types[fork]
