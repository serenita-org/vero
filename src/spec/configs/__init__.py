from enum import Enum
from pathlib import Path
from typing import Any

from yaml import BaseLoader, load

from spec.base import SpecFulu, parse_spec


class Network(Enum):
    MAINNET = "mainnet"
    HOLESKY = "holesky"
    HOODI = "hoodi"

    GNOSIS = "gnosis"
    CHIADO = "chiado"

    # Special case that should only be used to execute
    #  Vero's automated test suite
    _TESTS = "_tests"

    # Special case where Vero loads a custom network config from the filesystem
    CUSTOM = "custom"


def parse_yaml_file(fp: Path) -> dict[str, Any]:
    with Path.open(fp) as f:
        parsed = load(f, BaseLoader)  # noqa: S506 - trusted input, and BaseLoader is also safe
        if not isinstance(parsed, dict):
            raise TypeError(f"Expected a dict, got {type(parsed)}")
        return parsed


def get_network_spec(
    network: Network, network_custom_config_path: str | None = None
) -> SpecFulu:
    spec_dict = {}

    if network == Network.CUSTOM:
        if network_custom_config_path is None:
            raise ValueError(
                "--network-custom-config-path must be specified for `custom` network"
            )
        spec_dict.update(parse_yaml_file(Path(network_custom_config_path)))
    else:
        spec_dict.update(
            parse_yaml_file(Path(__file__).parent / f"{network.value}.yaml")
        )

    preset_files_dir = (
        Path(__file__).parent / "presets" / f"{spec_dict['PRESET_BASE'].strip("'")}"
    )
    for fname in preset_files_dir.iterdir():
        spec_dict.update(
            parse_yaml_file(
                Path(preset_files_dir) / fname,
            )
        )

    return parse_spec(data=spec_dict)
