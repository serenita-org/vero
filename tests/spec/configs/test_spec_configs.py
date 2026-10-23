from typing import Any

import pytest

from spec.base import GasLimitScheduleEntry, SpecGloas, parse_spec
from spec.common import Uint64
from spec.configs import Network, get_network_spec


@pytest.mark.parametrize(
    argnames="network",
    argvalues=[network for network in Network if network != Network.CUSTOM],
)
def test_get_network_spec(network: Network) -> None:
    if network in (Network.MAINNET, Network.HOODI, Network.GNOSIS, Network.CHIADO):
        pytest.skip("Gloas configs not yet available yet for these networks")
    spec, preset = get_network_spec(network=network)
    assert isinstance(spec, SpecGloas)
    # There are only two presets Vero supports
    assert preset in ("mainnet", "gnosis")


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
    # Optional spec field must not cause consensus spec mismatches.
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
