import asyncio

import pytest
from aiointercept import aiointercept

from providers import RemoteSigner, Vero


async def test_remote_signer_healthcheck_not_supported(
    vero: Vero, remote_signer_mock: aiointercept, caplog: pytest.LogCaptureFixture
) -> None:
    signer_url = remote_signer_mock.server_url
    remote_signer_mock.get(f"{signer_url}/healthcheck", status=404)
    async with RemoteSigner(
        url=signer_url, vero=vero, process_pool_executor=None
    ) as signer:
        assert len(vero.task_manager._tasks) == 1
        poll_health_task = next(t for t in vero.task_manager._tasks)
        assert poll_health_task.get_name() == f"remote-signer-poll-health-{signer_url}"
        assert not poll_health_task.done()

        # Wait for the polling task to process the HTTP response and exit.
        await asyncio.wait_for(poll_health_task, timeout=0.5)

        # The endpoint returning 404 should disable the task
        assert any(
            f"Healthcheck endpoint returned 404 status code - disabling healthcheck polling for {signer.netloc}"
            in m
            for m in caplog.messages
        )

        # The task should no longer run
        assert len(vero.task_manager._tasks) == 0
        assert poll_health_task.done()
