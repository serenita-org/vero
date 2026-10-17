from pathlib import Path
from typing import Any

import pytest
import yaml

from spec.base import GasLimitScheduleEntry, SpecGloas, parse_spec
from spec.common import Uint64
from spec.configs import Network, get_network_spec, parse_yaml_file


@pytest.mark.parametrize(
    argnames="network",
    argvalues=[network for network in Network if network != Network.CUSTOM],
)
def test_get_network_spec(network: Network) -> None:
    if network in (Network.MAINNET, Network.GNOSIS, Network.CHIADO):
        pytest.skip("Gloas configs not yet available yet for these networks")
    spec, preset = get_network_spec(network=network)
    assert isinstance(spec, SpecGloas)
    # There are only two presets Vero supports
    assert preset in ("mainnet", "gnosis")


def test_gas_limit_schedule_config(tmp_path: Path) -> None:
    config_path = Path(__file__).parents[3] / "src/spec/configs/_tests.yaml"
    config = parse_yaml_file(config_path)
    config["GAS_LIMIT_SCHEDULE"] = [
        {"EPOCH": 10, "GAS_LIMIT": 60_000_000},
        {"EPOCH": 20, "GAS_LIMIT": 75_000_000},
    ]
    custom_config = tmp_path / "config.yaml"
    custom_config.write_text(yaml.safe_dump(config))

    spec, _ = get_network_spec(Network.CUSTOM, str(custom_config))
    expected_schedule = [
        GasLimitScheduleEntry(Uint64(10), Uint64(60_000_000)),
        GasLimitScheduleEntry(Uint64(20), Uint64(75_000_000)),
    ]
    assert expected_schedule == spec.GAS_LIMIT_SCHEDULE
    serialized = spec.to_obj()
    assert serialized["GAS_LIMIT_SCHEDULE"] == [
        {"EPOCH": "10", "GAS_LIMIT": "60000000"},
        {"EPOCH": "20", "GAS_LIMIT": "75000000"},
    ]
    assert parse_spec(serialized).GAS_LIMIT_SCHEDULE == spec.GAS_LIMIT_SCHEDULE


@pytest.mark.parametrize("schedule", [None, []])
def test_optional_gas_limit_schedule(schedule: list[Any] | None) -> None:
    spec, _ = get_network_spec(Network._TESTS)
    data = spec.to_obj()
    if schedule is None:
        del data["GAS_LIMIT_SCHEDULE"]
    else:
        data["GAS_LIMIT_SCHEDULE"] = schedule
    parsed = parse_spec(data)
    assert parsed.GAS_LIMIT_SCHEDULE == []
    assert parsed.get_scheduled_gas_limit(200_000) is None
    # Optional recommendations must not cause consensus spec mismatches.
    assert parsed == spec


@pytest.mark.parametrize(
    ("epoch", "expected"),
    [
        (4, None),
        (5, 30_000_000),
        (9, 30_000_000),
        (10, 60_000_000),
        (19, 60_000_000),
        (20, 75_000_000),
        (100, 75_000_000),
    ],
)
def test_scheduled_gas_limit(epoch: int, expected: int | None) -> None:
    spec, _ = get_network_spec(Network._TESTS)
    spec.GLOAS_FORK_EPOCH = Uint64(5)
    # Entries need not be sorted; pre-fork entries become usable at Gloas.
    spec.GAS_LIMIT_SCHEDULE = [
        GasLimitScheduleEntry(Uint64(20), Uint64(75_000_000)),
        GasLimitScheduleEntry(Uint64(0), Uint64(30_000_000)),
        GasLimitScheduleEntry(Uint64(10), Uint64(60_000_000)),
    ]
    assert spec.get_scheduled_gas_limit(epoch) == expected


def test_no_active_gas_limit_schedule_entry() -> None:
    spec, _ = get_network_spec(Network._TESTS)
    assert spec.get_scheduled_gas_limit(0) is None


@pytest.mark.parametrize("field", ["EPOCH", "GAS_LIMIT"])
@pytest.mark.parametrize("value", ["-1", str(2**64)])
def test_gas_limit_schedule_uint64_validation(field: str, value: str) -> None:
    spec, _ = get_network_spec(Network._TESTS)
    data = spec.to_obj()
    data["GAS_LIMIT_SCHEDULE"] = [{"EPOCH": "0", "GAS_LIMIT": "60000000", field: value}]
    with pytest.raises(ValueError, match="uint64 value out of range"):
        parse_spec(data)
