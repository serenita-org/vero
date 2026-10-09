from typing import get_args

import pytest
from spy_ssz import Fork

from spec import Preset, initialize_preset, preset_types


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
            types.attestation.expected_preset.name.lower(),
            types.aggregate_and_proof.expected_preset.name.lower(),
            types.sync_committee_contribution.expected_preset.name.lower(),
            types.contribution_and_proof.expected_preset.name.lower(),
            types.single_attestation.expected_preset.name.lower(),
            types.sync_committee_message.expected_preset.name.lower(),
            types.signed_aggregate_and_proof.expected_preset.name.lower(),
            types.signed_contribution_and_proof.expected_preset.name.lower(),
        } == {preset}

        with pytest.raises(ValueError, match="status=MALFORMED_INPUT"):
            types.attestation_data.from_json(b"{}")
    finally:
        initialize_preset("mainnet")
