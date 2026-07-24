import pytest

from spec import Preset, initialize_preset, preset_types


@pytest.mark.parametrize("preset", ["mainnet", "minimal", "gnosis"])
def test_initialize_preset_selects_one_coherent_type_bundle(preset: Preset) -> None:
    try:
        initialize_preset(preset)
        types = preset_types()

        assert types.preset == preset
        assert {
            types.attestation.expected_preset.name.lower(),
            types.aggregate_and_proof.expected_preset.name.lower(),
            types.block_contents.expected_preset.name.lower(),
            types.signed_block_contents.expected_preset.name.lower(),
            types.blinded_block.expected_preset.name.lower(),
            types.signed_blinded_block.expected_preset.name.lower(),
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
