import time
from enum import Enum
from pathlib import Path
from typing import Any

from yaml import BaseLoader, load

from spec.base import Genesis, SpecFulu, parse_spec


class Network(Enum):
    MAINNET = "mainnet"
    HOODI = "hoodi"

    GNOSIS = "gnosis"
    CHIADO = "chiado"

    # Special case that should only be used to execute
    #  Vero's automated test suite
    _TESTS = "_tests"

    # Special case where Vero loads a custom network config from the filesystem
    CUSTOM = "custom"


def get_genesis_for_network(network: Network) -> Genesis:
    if network == Network.CUSTOM:
        # For custom networks, genesis data is retrieved on-demand
        # from the primary beacon node.
        raise NotImplementedError

    genesis_mapping = {
        Network.MAINNET: (
            1606824023,
            "0x4b363db94e286120d76eb905340fdd4e54bfe9f06bf33ff6cf5ad27f511bfe95",
            "0x00000000",
        ),
        Network.HOODI: (
            1742213400,
            "0x212f13fc4df078b6cb7db228f1c8307566dcecf900867401a92023d7ba99cb5f",
            "0x10000910",
        ),
        Network.GNOSIS: (
            1638993340,
            "0xf5dcb5564e829aab27264b9becd5dfaa017085611224cb3036f573368dbb9d47",
            "0x00000064",
        ),
        Network.CHIADO: (
            1665396300,
            "0x9d642dac73058fbf39c0ae41ab1e34e4d889043cb199851ded7095bc99eb4c1e",
            "0x0000006f",
        ),
        # Fake genesis 1 hour ago for tests
        Network._TESTS: (int(time.time() - 3600), "0x" + "0" * 64, "0xffffffff"),  # noqa: SLF001
    }
    g_time, val_root, fork_version = genesis_mapping[network]
    return Genesis(
        genesis_time=g_time,
        genesis_validators_root=val_root,
        genesis_fork_version=fork_version,
    )


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
