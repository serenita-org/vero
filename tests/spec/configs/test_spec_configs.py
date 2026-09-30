from pathlib import Path

import pytest

from spec.base import SpecFulu
from spec.configs import Network, get_network_spec

MAINNET_CONFIG = Path(__file__).parents[3] / "src" / "spec" / "configs" / "mainnet.yaml"


def _custom_config_without_seconds_per_slot(
    tmp_path: Path, slot_duration_ms: int
) -> Path:
    lines = [
        line
        for line in MAINNET_CONFIG.read_text().splitlines()
        if not line.startswith(("SECONDS_PER_SLOT:", "SLOT_DURATION_MS:"))
    ]
    lines.append(f"SLOT_DURATION_MS: {slot_duration_ms}")
    config_path = tmp_path / "config.yaml"
    config_path.write_text("\n".join(lines) + "\n")
    return config_path


@pytest.mark.parametrize(
    argnames="network",
    argvalues=[network for network in Network if network != Network.CUSTOM],
)
def test_get_network_spec(network: Network) -> None:
    spec, preset = get_network_spec(network=network)
    assert isinstance(spec, SpecFulu)
    # There are only two presets Vero supports
    assert preset in ("mainnet", "gnosis")


def test_get_network_spec_derives_seconds_per_slot(tmp_path: Path) -> None:
    config_path = _custom_config_without_seconds_per_slot(tmp_path, 6000)
    spec, _ = get_network_spec(
        network=Network.CUSTOM, network_custom_config_path=str(config_path)
    )
    assert spec.SECONDS_PER_SLOT == 6


def test_get_network_spec_rejects_sub_second_slot_duration(tmp_path: Path) -> None:
    config_path = _custom_config_without_seconds_per_slot(tmp_path, 1500)
    with pytest.raises(ValueError, match="not a whole number of seconds"):
        get_network_spec(
            network=Network.CUSTOM, network_custom_config_path=str(config_path)
        )
