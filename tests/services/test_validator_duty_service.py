import asyncio

import pytest

from services.validator_duty_service import (
    ValidatorDutyService,
    ValidatorDutyServiceOptions,
)


class MockValidatorDutyService(ValidatorDutyService):
    pass


@pytest.fixture
def mock_validator_duty_service(
    validator_duty_service_options: ValidatorDutyServiceOptions,
) -> MockValidatorDutyService:
    return MockValidatorDutyService(**validator_duty_service_options)


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
    mock_validator_duty_service: MockValidatorDutyService,
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
    ) in mock_validator_duty_service._iter_fast_then_slow_task_batches(
        tasks=[
            asyncio.create_task(_complete_after(task_1_delay, "task1")),
            asyncio.create_task(_complete_after(task_2_delay, "task2")),
        ],
        fast_wait_s=fast_wait_time_s,
    ):
        observed_batches.append((is_slow_batch, [await future for future in batch]))

    assert observed_batches == expected_batches
