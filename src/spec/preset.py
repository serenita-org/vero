from dataclasses import dataclass
from typing import Literal, cast

from spy_ssz import (
    AggregateAndProofElectra,
    AggregateAndProofFulu,
    AggregateAndProofGloas,
    AttestationDataElectra,
    AttestationDataFulu,
    AttestationDataGloas,
    AttestationElectra,
    AttestationFulu,
    AttestationGloas,
    ContributionAndProofElectra,
    ContributionAndProofFulu,
    ContributionAndProofGloas,
    Fork,
    Preset as SpyPreset,
    SignedAggregateAndProofElectra,
    SignedAggregateAndProofFulu,
    SignedAggregateAndProofGloas,
    SignedContributionAndProofElectra,
    SignedContributionAndProofFulu,
    SignedContributionAndProofGloas,
    SingleAttestationElectra,
    SingleAttestationFulu,
    SingleAttestationGloas,
    SszObject,
    SyncCommitteeContributionElectra,
    SyncCommitteeContributionFulu,
    SyncCommitteeContributionGloas,
    SyncCommitteeMessageElectra,
    SyncCommitteeMessageFulu,
    SyncCommitteeMessageGloas,
    get_ssz_type,
)
from spy_ssz.electra import (
    BeaconBlockContentsElectra,
    BlindedBeaconBlockElectra,
    SignedBeaconBlockContentsElectra,
    SignedBlindedBeaconBlockElectra,
)
from spy_ssz.fulu import (
    BeaconBlockContentsFulu,
    BlindedBeaconBlockFulu,
    SignedBeaconBlockContentsFulu,
    SignedBlindedBeaconBlockFulu,
)
from spy_ssz.gloas import BeaconBlockGloas, SignedBeaconBlockGloas
from spy_ssz.projections import Checkpoint as Checkpoint

Preset = Literal["mainnet", "minimal", "gnosis"]
AttestationData = AttestationDataElectra | AttestationDataFulu | AttestationDataGloas
Attestation = AttestationElectra | AttestationFulu | AttestationGloas
AggregateAndProof = (
    AggregateAndProofElectra | AggregateAndProofFulu | AggregateAndProofGloas
)
SyncCommitteeContribution = (
    SyncCommitteeContributionElectra
    | SyncCommitteeContributionFulu
    | SyncCommitteeContributionGloas
)
ContributionAndProof = (
    ContributionAndProofElectra | ContributionAndProofFulu | ContributionAndProofGloas
)
SingleAttestation = (
    SingleAttestationElectra | SingleAttestationFulu | SingleAttestationGloas
)
SyncCommitteeMessage = (
    SyncCommitteeMessageElectra | SyncCommitteeMessageFulu | SyncCommitteeMessageGloas
)
SignedAggregateAndProof = (
    SignedAggregateAndProofElectra
    | SignedAggregateAndProofFulu
    | SignedAggregateAndProofGloas
)
SignedContributionAndProof = (
    SignedContributionAndProofElectra
    | SignedContributionAndProofFulu
    | SignedContributionAndProofGloas
)
BeaconBlock = (
    BeaconBlockContentsElectra
    | BlindedBeaconBlockElectra
    | BeaconBlockContentsFulu
    | BlindedBeaconBlockFulu
    | BeaconBlockGloas
)
SignedBeaconBlock = (
    SignedBeaconBlockContentsElectra
    | SignedBlindedBeaconBlockElectra
    | SignedBeaconBlockContentsFulu
    | SignedBlindedBeaconBlockFulu
    | SignedBeaconBlockGloas
)


@dataclass(frozen=True)
class PresetTypes:
    preset: Preset
    fork: Fork
    attestation_data: type[AttestationData]
    attestation: type[Attestation]
    aggregate_and_proof: type[AggregateAndProof]
    sync_committee_contribution: type[SyncCommitteeContribution]
    contribution_and_proof: type[ContributionAndProof]
    single_attestation: type[SingleAttestation]
    sync_committee_message: type[SyncCommitteeMessage]
    signed_aggregate_and_proof: type[SignedAggregateAndProof]
    signed_contribution_and_proof: type[SignedContributionAndProof]


def _resolve_type(
    preset: SpyPreset,
    expected_type: type[SszObject],
) -> type[SszObject]:
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


_active_types: dict[Fork, PresetTypes] = {}


def _initialize_fork_types(
    *,
    preset: Preset,
    spy_preset: SpyPreset,
    fork: Fork,
) -> PresetTypes:
    type_names = {
        Fork.ELECTRA: (
            AttestationDataElectra,
            AttestationElectra,
            AggregateAndProofElectra,
            SyncCommitteeContributionElectra,
            ContributionAndProofElectra,
            SingleAttestationElectra,
            SyncCommitteeMessageElectra,
            SignedAggregateAndProofElectra,
            SignedContributionAndProofElectra,
        ),
        Fork.FULU: (
            AttestationDataFulu,
            AttestationFulu,
            AggregateAndProofFulu,
            SyncCommitteeContributionFulu,
            ContributionAndProofFulu,
            SingleAttestationFulu,
            SyncCommitteeMessageFulu,
            SignedAggregateAndProofFulu,
            SignedContributionAndProofFulu,
        ),
        Fork.GLOAS: (
            AttestationDataGloas,
            AttestationGloas,
            AggregateAndProofGloas,
            SyncCommitteeContributionGloas,
            ContributionAndProofGloas,
            SingleAttestationGloas,
            SyncCommitteeMessageGloas,
            SignedAggregateAndProofGloas,
            SignedContributionAndProofGloas,
        ),
    }
    (
        attestation_data,
        attestation,
        aggregate_and_proof,
        sync_committee_contribution,
        contribution_and_proof,
        single_attestation,
        sync_committee_message,
        signed_aggregate_and_proof,
        signed_contribution_and_proof,
    ) = type_names[fork]
    return PresetTypes(
        preset=preset,
        fork=fork,
        attestation_data=cast(
            "type[AttestationData]",
            _resolve_type(spy_preset, attestation_data),
        ),
        attestation=cast(
            "type[Attestation]",
            _resolve_type(spy_preset, attestation),
        ),
        aggregate_and_proof=cast(
            "type[AggregateAndProof]",
            _resolve_type(spy_preset, aggregate_and_proof),
        ),
        sync_committee_contribution=cast(
            "type[SyncCommitteeContribution]",
            _resolve_type(spy_preset, sync_committee_contribution),
        ),
        contribution_and_proof=cast(
            "type[ContributionAndProof]",
            _resolve_type(spy_preset, contribution_and_proof),
        ),
        single_attestation=cast(
            "type[SingleAttestation]",
            _resolve_type(spy_preset, single_attestation),
        ),
        sync_committee_message=cast(
            "type[SyncCommitteeMessage]",
            _resolve_type(spy_preset, sync_committee_message),
        ),
        signed_aggregate_and_proof=cast(
            "type[SignedAggregateAndProof]",
            _resolve_type(spy_preset, signed_aggregate_and_proof),
        ),
        signed_contribution_and_proof=cast(
            "type[SignedContributionAndProof]",
            _resolve_type(spy_preset, signed_contribution_and_proof),
        ),
    )


def initialize_preset(preset: Preset) -> None:
    global _active_types
    spy_preset = SpyPreset[preset.upper()]
    _active_types = {
        fork: _initialize_fork_types(
            preset=preset,
            spy_preset=spy_preset,
            fork=fork,
        )
        for fork in (Fork.ELECTRA, Fork.FULU, Fork.GLOAS)
    }


def preset_types(fork: Fork = Fork.FULU) -> PresetTypes:
    if not _active_types:
        raise RuntimeError("initialize_preset was not called")
    return _active_types[fork]
