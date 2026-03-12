import asyncio
import cProfile
import logging
import os
import pstats
import signal
import time
from _lsprof import profiler_entry
from collections.abc import Generator

import pytest

from main import main
from providers import Vero
from schemas.beacon_api import ForkVersion


@pytest.fixture
def _profile_program_run() -> Generator[None, None, None]:
    # CI environments report artificially high CPU usage due to virtualization
    # -> skipping the check of CPU usage there
    if os.getenv("CI") == "true":
        yield
        return

    def is_idle_stat(stat: profiler_entry) -> bool:
        """
        Some stats are treated as 'idle time' when evaluating CPU usage,
        since the program is waiting on I/O and not actively consuming CPU.
        """
        if isinstance(stat.code, str):
            return any(
                substr in stat.code
                for substr in (
                    "of 'select.kqueue' objects>",
                    "of 'select.poll' objects>",
                )
            )
        return False

    prof = cProfile.Profile()
    with prof:
        start_wall_time = time.perf_counter()
        yield
        wall_time = time.perf_counter() - start_wall_time

    idle_time = sum(s.totaltime for s in prof.getstats() if is_idle_stat(s))
    adjusted_cpu_time = pstats.Stats(prof).total_tt - idle_time  # type: ignore[attr-defined]
    cpu_utilization = adjusted_cpu_time / wall_time

    # Vero should be able to perform all its duties without
    # keeping the event loop busy 100% of the time, even with
    # the very short 1s slot time in the test config.
    assert 0.02 < cpu_utilization < 0.5


@pytest.mark.parametrize(
    "enable_keymanager_api",
    [
        pytest.param(False, id="signature_provider: RemoteSigner"),
        pytest.param(True, id="signature_provider: Keymanager"),
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    "fork_version",
    [
        pytest.param(ForkVersion.ELECTRA, id="Electra"),
        pytest.param(ForkVersion.FULU, id="Fulu"),
        pytest.param(ForkVersion.GLOAS, id="Gloas"),
    ],
    indirect=True,
)
@pytest.mark.usefixtures("_mocked_beacon_node_endpoints")
@pytest.mark.usefixtures("_mocked_remote_signer_endpoints")
@pytest.mark.usefixtures("_profile_program_run")
@pytest.mark.usefixtures("_unregister_prometheus_metrics")
async def test_lifecycle(
    vero: Vero,
    enable_keymanager_api: bool,
    fork_version: ForkVersion,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Sanity check that Vero can start running, perform its duties and shut down cleanly.
    """
    run_services_task = asyncio.create_task(main(vero=vero))

    # Wait for expected log lines to appear
    required_log_lines = [
        "Initialized beacon node",
        "Current slot: ",
        "Started validator duty services",
        "Subscribing to events",
    ]

    if enable_keymanager_api:
        # It's not that easy to register validator keys from inside this test
        # for the Keymanager mode. So we'll not actually expect to perform duties
        # from within this test.
        required_log_lines.append("No active or pending validators detected")
    else:
        required_log_lines.extend(
            [
                "Validators: 4 active, 1 pending (total: 5)",
                "Updated duties",
                "Published block for slot",
                "Published attestations for slot",
                "Published sync committee messages for slot",
            ]
        )

    timeout = 5
    start = asyncio.get_running_loop().time()

    all_lines_present = False
    while asyncio.get_running_loop().time() - start < timeout:
        await asyncio.sleep(0.2)

        # Check if every required substring appears at least once in the captured logs
        if all(
            any(line in message for message in caplog.messages)
            for line in required_log_lines
        ):
            all_lines_present = True
            break

    assert all_lines_present, (
        f"Log lines not found: {[line for line in required_log_lines if not any(line in m for m in caplog.messages)]}"
    )

    # Make sure no unexpected errors occurred
    err_records = [r for r in caplog.records if r.levelno == logging.ERROR]

    unexpected_err_messages = []
    for record in err_records:
        # Event stream is not mocked
        if "Error occurred while processing beacon node events" in record.message:
            continue

        unexpected_err_messages.append(record.message)

    if unexpected_err_messages:
        pytest.fail(f"Unexpected errors occurred: {unexpected_err_messages}")

    # Send SIGTERM signal to process to initiate a clean shutdown
    os.kill(os.getpid(), signal.SIGTERM)

    await vero.shutdown_event.wait()
    await run_services_task

    assert any("Received shutdown signal SIGTERM" in m for m in caplog.messages)
    assert any("Shutting down" in m for m in caplog.messages)
