import os
from enum import Enum
from pathlib import Path

from spec.base import Spec, parse_spec


class Network(Enum):
    MAINNET = "mainnet"
    GNOSIS = "gnosis"
    HOLESKY = "holesky"

    # Special case where Vero uses the network specs returned by the beacon node(s)
    FETCH = "fetch"


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


def get_network_spec(network: Network) -> Spec:
    spec_dict = {}

    spec_dict.update(parse_yaml_file(Path(__file__).parent / f"{network.value}.yaml"))

    preset_files_dir = (
        Path(__file__).parent / "presets" / f"{spec_dict['PRESET_BASE'].strip("'")}"
    )
    for fname in os.listdir(preset_files_dir):
        spec_dict.update(
            parse_yaml_file(
                Path(preset_files_dir) / fname,
            )
        )

    return parse_spec(data=spec_dict)
