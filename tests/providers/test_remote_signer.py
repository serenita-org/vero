import asyncio
import re

import pytest
from aioresponses import aioresponses

from providers import RemoteSigner, Vero


async def test_remote_signer_healtcheck_not_supported(
    vero: Vero, caplog: pytest.LogCaptureFixture
) -> None:
    signer_url = "http://signer:9000"
    with aioresponses() as m:
        m.get(re.compile(f"{signer_url}/healthcheck"), status=404)
        async with RemoteSigner(url=signer_url, vero=vero, process_pool_executor=None):
            assert len(vero.task_manager._tasks) == 1
            poll_health_task = next(t for t in vero.task_manager._tasks)
            assert (
                poll_health_task.get_name()
                == "remote-signer-poll-health-http://signer:9000"
            )
            assert not poll_health_task.done()

            # Yield to event loop to allow the healthcheck task to start running
            await asyncio.sleep(0.001)

            # The endpoint returning 404 should disable the task
            assert any(
                "Healthcheck endpoint returned 404 status code - disabling healthcheck polling for signer"
                in m
                for m in caplog.messages
            )

            # The task should no longer run
            assert len(vero.task_manager._tasks) == 0
            assert poll_health_task.done()
