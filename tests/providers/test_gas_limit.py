import pytest

from providers import Keymanager, Vero
from spec.base import GasLimitScheduleEntry
from spec.common import Uint64
from spec.configs import Network


@pytest.mark.parametrize(
    ("network", "expected"),
    [
        (Network.MAINNET, 60_000_000),
        (Network.HOODI, 60_000_000),
        (Network.GNOSIS, 17_000_000),
        (Network.CHIADO, 17_000_000),
        (Network.CUSTOM, 100_000_000),
    ],
)
@pytest.mark.parametrize("schedule_active", [False, True])
async def test_gas_limit_defaults(
    keymanager: Keymanager,
    vero: Vero,
    network: Network,
    expected: int,
    schedule_active: bool,
) -> None:
    vero.cli_args.network = network
    vero.cli_args.gas_limit = None
    vero.spec.GLOAS_FORK_EPOCH = Uint64(5)
    vero.spec.GAS_LIMIT_SCHEDULE = [
        GasLimitScheduleEntry(Uint64(10), Uint64(75_000_000))
    ]
    slots_per_epoch = keymanager.beacon_chain.SLOTS_PER_EPOCH
    for epoch in (0, 5, 9):
        assert keymanager.get_effective_gas_limit(
            "pubkey", epoch * slots_per_epoch
        ) == str(expected)
    if not schedule_active:
        vero.spec.GAS_LIMIT_SCHEDULE = []
    for epoch in (10, 11):
        assert keymanager.get_effective_gas_limit(
            "pubkey", epoch * slots_per_epoch
        ) == str(75_000_000 if schedule_active else expected)


@pytest.mark.parametrize(
    ("configured", "override", "expected", "warns"),
    [
        (None, None, 60_000_000, False),
        (60_000_000, None, 60_000_000, False),
        (90_000_000, None, 90_000_000, True),
        (50_000_000, None, 50_000_000, False),
        (90_000_000, "50000000", 50_000_000, False),
        (50_000_000, "90000000", 90_000_000, True),
        (None, "0", 0, False),
    ],
)
async def test_gas_limit_overrides(
    keymanager: Keymanager,
    vero: Vero,
    configured: int | None,
    override: str | None,
    expected: int,
    warns: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    vero.cli_args.gas_limit = configured
    vero.spec.GAS_LIMIT_SCHEDULE = [
        GasLimitScheduleEntry(Uint64(10), Uint64(60_000_000))
    ]
    keymanager.enabled = True
    if override is not None:
        keymanager.pubkey_to_gas_limit_override["pubkey"] = override
    slot = 10 * keymanager.beacon_chain.SLOTS_PER_EPOCH
    assert keymanager.get_effective_gas_limit("pubkey", slot) == str(expected)
    warnings = [m for m in caplog.messages if "exceeds the recommended maximum" in m]
    assert bool(warnings) == warns
    if warns:
        assert str(expected) in warnings[0]
        assert "60000000 at epoch 10" in warnings[0]
        assert "pubkey" in warnings[0]


async def test_configured_gas_limit_without_active_schedule(
    keymanager: Keymanager,
    vero: Vero,
    caplog: pytest.LogCaptureFixture,
) -> None:
    vero.cli_args.gas_limit = 90_000_000
    vero.spec.GLOAS_FORK_EPOCH = Uint64(10)
    vero.spec.GAS_LIMIT_SCHEDULE = [
        GasLimitScheduleEntry(Uint64(0), Uint64(60_000_000))
    ]
    assert keymanager.get_effective_gas_limit("pubkey", 0) == "90000000"
    vero.spec.GAS_LIMIT_SCHEDULE = []
    assert (
        keymanager.get_effective_gas_limit(
            "pubkey", 10 * keymanager.beacon_chain.SLOTS_PER_EPOCH
        )
        == "90000000"
    )
    assert not any("exceeds the recommended maximum" in m for m in caplog.messages)
