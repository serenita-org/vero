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

from args import CLIArgs
from main import main


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
@pytest.mark.usefixtures("_mocked_beacon_node_endpoints")
@pytest.mark.usefixtures("_mocked_remote_signer_endpoints")
@pytest.mark.usefixtures("_profile_program_run")
@pytest.mark.usefixtures("_unregister_prometheus_metrics")
async def test_lifecycle(
    cli_args: CLIArgs,
    shutdown_event: asyncio.Event,
    enable_keymanager_api: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Sanity check that Vero can start running, perform its duties and shut down cleanly.
    """
    run_services_task = asyncio.create_task(
        main(
            cli_args=cli_args,
            shutdown_event=shutdown_event,
        )
    )

    # Wait for expected log lines to appear
    required_log_lines = [
        "Initialized beacon node",
        "Current slot: ",
        "Initialized validator status tracker",
        "Started validator duty services",
        "Subscribing to events",
        "Updated duties",
        "Published block for slot",
        "Published attestations for slot",
        "Published sync committee messages for slot",
    ]

    if enable_keymanager_api:
        # Slightly fewer checks for this mode since it's not that easy
        # to register validator keys from inside this test
        for line in (
            "Updated duties",
            "Published block for slot",
            "Published attestations for slot",
            "Published sync committee messages for slot",
        ):
            required_log_lines.remove(line)

        required_log_lines.append("No active or pending validators detected")

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

    # Make sure no errors occurred
    err_records = [r for r in caplog.records if r.levelno == logging.ERROR]

    for record in err_records:
        # Event stream is not mocked
        if "Error occurred while processing beacon node events" in record.message:
            continue

        pytest.fail(f"Error occurred: {record.message}")

    # Send SIGTERM signal to process to initiate a clean shutdown
    os.kill(os.getpid(), signal.SIGTERM)

    await shutdown_event.wait()
    await run_services_task

    assert any("Received shutdown signal SIGTERM" in m for m in caplog.messages)
    assert any("Shutting down" in m for m in caplog.messages)
