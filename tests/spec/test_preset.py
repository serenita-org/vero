from typing import get_args

import pytest

from spec import Preset, initialize_preset, preset_types
from spec.ssz import Fork


@pytest.mark.parametrize("preset", get_args(Preset))
@pytest.mark.parametrize("fork", [Fork.ELECTRA, Fork.FULU, Fork.GLOAS])
def test_initialize_preset_selects_one_coherent_type_bundle(
    preset: Preset,
    fork: Fork,
) -> None:
    try:
        initialize_preset(preset)
        types = preset_types(fork)

        assert types.preset == preset
        assert types.fork is fork
        assert {
            types.attestation.preset,
            types.aggregate_and_proof.preset,
            types.sync_committee_contribution.preset,
            types.contribution_and_proof.preset,
            types.single_attestation.preset,
            types.sync_committee_message.preset,
            types.signed_aggregate_and_proof.preset,
            types.signed_contribution_and_proof.preset,
        } == {preset}

        with pytest.raises(ValueError, match="missing fields"):
            types.attestation_data.from_json(b"{}")
    finally:
        initialize_preset("mainnet")
