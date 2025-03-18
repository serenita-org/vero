from enum import Enum
from pathlib import Path

from spec.base import Spec, parse_spec


class Network(Enum):
    MAINNET = "mainnet"
    HOLESKY = "holesky"

    GNOSIS = "gnosis"
    CHIADO = "chiado"

    # Special case that should only be used to execute
    #  Vero's automated test suite
    _TESTS = "_tests"

    # Special case where Vero loads a custom network config from the filesystem
    CUSTOM = "custom"


def parse_yaml_file(fp: Path) -> dict[str, str]:
    return_dict: dict[str, str] = {}
    with Path.open(fp) as f:
        for line in f:
            line = line.strip().split("#", maxsplit=1)[0]
            if line == "":
                continue

            name, value = line.split(": ", maxsplit=1)
            if name in return_dict:
                raise ValueError(f"{name} already defined as {return_dict[name]}")
            return_dict[name] = value.strip()
    return return_dict


def get_network_spec(
    network: Network, network_custom_config_path: str | None = None
) -> Spec:
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
