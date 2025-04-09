import asyncio
import logging
import os
import signal

import pytest

from args import CLIArgs
from main import main


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
async def test_lifecycle(
    cli_args: CLIArgs,
    shutdown_event: asyncio.Event,
    enable_keymanager_api: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Sanity check that Vero can start running and shut down cleanly.
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
