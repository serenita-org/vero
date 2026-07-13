from dataclasses import dataclass
from typing import Literal

from spy_ssz import (
    AggregateAndProof,
    Attestation,
    AttestationData,
    ContributionAndProof,
    SignedAggregateAndProof,
    SignedContributionAndProof,
    SingleAttestation,
    SszObject,
    SyncCommitteeContribution,
    SyncCommitteeMessage,
    get_ssz_type,
)
from spy_ssz import (
    Preset as SpyPreset,
)
from spy_ssz.electra import (
    ElectraBeaconBlockContents,
    ElectraBlindedBeaconBlock,
    ElectraSignedBeaconBlockContents,
    ElectraSignedBlindedBeaconBlock,
)
from spy_ssz.fulu import (
    FuluBeaconBlockContents,
    FuluBlindedBeaconBlock,
    FuluSignedBeaconBlockContents,
    FuluSignedBlindedBeaconBlock,
)
from spy_ssz.projections import Checkpoint

Preset = Literal["mainnet", "minimal", "gnosis"]
BeaconBlock = (
    ElectraBeaconBlockContents
    | ElectraBlindedBeaconBlock
    | FuluBeaconBlockContents
    | FuluBlindedBeaconBlock
)
SignedBeaconBlock = (
    ElectraSignedBeaconBlockContents
    | ElectraSignedBlindedBeaconBlock
    | FuluSignedBeaconBlockContents
    | FuluSignedBlindedBeaconBlock
)


@dataclass(frozen=True)
class PresetTypes:
    preset: Preset
    attestation_data: type[AttestationData]
    attestation: type[Attestation]
    aggregate_and_proof: type[AggregateAndProof]
    block_contents: type[ElectraBeaconBlockContents]
    signed_block_contents: type[ElectraSignedBeaconBlockContents]
    blinded_block: type[ElectraBlindedBeaconBlock]
    signed_blinded_block: type[ElectraSignedBlindedBeaconBlock]
    sync_committee_contribution: type[SyncCommitteeContribution]
    contribution_and_proof: type[ContributionAndProof]
    single_attestation: type[SingleAttestation]
    sync_committee_message: type[SyncCommitteeMessage]
    signed_aggregate_and_proof: type[SignedAggregateAndProof]
    signed_contribution_and_proof: type[SignedContributionAndProof]


def _resolve_type[SszObjectT: SszObject](
    preset: SpyPreset,
    expected_type: type[SszObjectT],
) -> type[SszObjectT]:
    fork = expected_type.expected_fork
    kind = expected_type.expected_kind
    if fork is None or kind is None:
        raise TypeError(f"{expected_type.__name__} is not a concrete SSZ type")

    resolved = get_ssz_type(fork, kind, preset)
    if not issubclass(resolved, expected_type):
        raise TypeError(
            f"Resolved {resolved.__name__} for {kind.name}/{preset.name}, "
            f"expected a {expected_type.__name__} subtype"
        )
    return resolved


_active_types: PresetTypes | None = None


def initialize_preset(preset: Preset) -> None:
    global _active_types
    spy_preset = SpyPreset[preset.upper()]
    _active_types = PresetTypes(
        preset=preset,
        attestation_data=_resolve_type(spy_preset, AttestationData),
        attestation=_resolve_type(spy_preset, Attestation),
        aggregate_and_proof=_resolve_type(spy_preset, AggregateAndProof),
        block_contents=_resolve_type(spy_preset, ElectraBeaconBlockContents),
        signed_block_contents=_resolve_type(
            spy_preset,
            ElectraSignedBeaconBlockContents,
        ),
        blinded_block=_resolve_type(spy_preset, ElectraBlindedBeaconBlock),
        signed_blinded_block=_resolve_type(
            spy_preset,
            ElectraSignedBlindedBeaconBlock,
        ),
        sync_committee_contribution=_resolve_type(
            spy_preset,
            SyncCommitteeContribution,
        ),
        contribution_and_proof=_resolve_type(spy_preset, ContributionAndProof),
        single_attestation=_resolve_type(spy_preset, SingleAttestation),
        sync_committee_message=_resolve_type(spy_preset, SyncCommitteeMessage),
        signed_aggregate_and_proof=_resolve_type(
            spy_preset,
            SignedAggregateAndProof,
        ),
        signed_contribution_and_proof=_resolve_type(
            spy_preset,
            SignedContributionAndProof,
        ),
    )


def preset_types() -> PresetTypes:
    if _active_types is None:
        raise RuntimeError("initialize_preset was not called")
    return _active_types


__all__ = [
    "AttestationData",
    "BeaconBlock",
    "Checkpoint",
    "Preset",
    "PresetTypes",
    "SignedAggregateAndProof",
    "SignedBeaconBlock",
    "SignedContributionAndProof",
    "SingleAttestation",
    "SyncCommitteeMessage",
    "initialize_preset",
    "preset_types",
]
