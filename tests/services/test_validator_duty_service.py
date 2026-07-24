import asyncio
import time

import pytest

from services.validator_duty_service import (
    ValidatorDutyService,
    ValidatorDutyServiceOptions,
)


class DutiesUpdater:
    def __init__(self) -> None:
        self.update_attempts = 0
        self.update_should_fail = False

    async def __call__(self) -> None:
        self.update_attempts += 1
        if self.update_should_fail:
            raise RuntimeError("Beacon node unavailable")


@pytest.fixture
def validator_duty_service(
    validator_duty_service_options: ValidatorDutyServiceOptions,
) -> ValidatorDutyService:
    return ValidatorDutyService(**validator_duty_service_options)


async def test_failed_duties_update_hands_off_at_epoch_boundary(
    validator_duty_service: ValidatorDutyService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duties_updater = DutiesUpdater()
    monkeypatch.setattr(validator_duty_service, "_update_duties", duties_updater)

    beacon_chain = validator_duty_service.beacon_chain
    next_epoch = beacon_chain.current_epoch + 1
    next_epoch_start = beacon_chain.get_timestamp_for_slot(
        beacon_chain.compute_start_slot_at_epoch(next_epoch)
    )

    # A failure with less than the initial backoff (1s) remaining should release the
    # lock instead of scheduling a retry that crosses the epoch boundary
    monkeypatch.setattr(time, "time", lambda: next_epoch_start - 0.5)
    duties_updater.update_should_fail = True
    async with asyncio.timeout(0.1):
        await validator_duty_service.update_duties()

    assert duties_updater.update_attempts == 1
    assert not validator_duty_service._update_duties_lock.locked()

    # The regular update at the new epoch can now acquire the lock and succeed
    monkeypatch.setattr(time, "time", lambda: float(next_epoch_start))
    duties_updater.update_should_fail = False
    await validator_duty_service.update_duties()

    assert duties_updater.update_attempts == 2


@pytest.mark.parametrize(
    argnames=("task_delays", "expected_batches"),
    argvalues=[
        pytest.param(
            (0.001, 0.010),
            [
                (False, ["task1", "task2"]),
            ],
            id="fast only",
        ),
        pytest.param(
            (0.025, 0.025),
            [
                (True, ["task1", "task2"]),
            ],
            id="slow only",
        ),
        pytest.param(
            (0.001, 0.025),
            [
                (False, ["task1"]),
                (True, ["task2"]),
            ],
            id="fast and slow",
        ),
    ],
)
async def test_iter_fast_then_slow_task_batches_yields_two_batches(
    task_delays: tuple[float, float],
    expected_batches: list[tuple[bool, list[str]]],
    validator_duty_service: ValidatorDutyService,
) -> None:
    async def _complete_after(delay: float, value: str) -> str:
        await asyncio.sleep(delay)
        return value

    task_1_delay, task_2_delay = task_delays
    fast_wait_time_s = 0.02

    observed_batches = []
    async for (
        is_slow_batch,
        batch,
    ) in validator_duty_service._iter_fast_then_slow_task_batches(
        tasks=[
            asyncio.create_task(_complete_after(task_1_delay, "task1")),
            asyncio.create_task(_complete_after(task_2_delay, "task2")),
        ],
        fast_wait_s=fast_wait_time_s,
    ):
        observed_batches.append(
            (is_slow_batch, sorted([await future for future in batch]))
        )

    assert observed_batches == expected_batches
