import contextlib
import re
from copy import copy

import pytest
from aioresponses import CallbackResult, aioresponses
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from providers import BeaconNode
from spec.base import SpecElectra, Version
from tasks import TaskManager


@pytest.mark.parametrize(
    "spec_mismatch",
    [
        pytest.param(False, id="match"),
        pytest.param(True, id="mismatch"),
    ],
)
async def test_initialize_spec_mismatch(
    spec_mismatch: bool,
    mocked_genesis_response: dict,  # type: ignore[type-arg]
    spec: SpecElectra,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
) -> None:
    """The BeaconNode should fail to initialize on a spec mismatch."""
    with contextlib.ExitStack() as stack:
        m = stack.enter_context(aioresponses())

        spec_to_return = spec
        if spec_mismatch:
            spec_to_return = copy(spec)
            spec_to_return.SLOTS_PER_EPOCH = 5
            spec_to_return.ELECTRA_FORK_VERSION = Version("0x00abcdef")

        m.get(
            url=re.compile(r"http://beacon-node-\w:1234/eth/v1/beacon/genesis"),
            callback=lambda *args, **kwargs: CallbackResult(
                payload=mocked_genesis_response,
            ),
        )
        m.get(
            url=re.compile(r"http://beacon-node-\w:1234/eth/v1/config/spec"),
            callback=lambda *args, **kwargs: CallbackResult(
                payload=dict(data=spec_to_return.to_obj()),
            ),
        )

        bn = BeaconNode(
            base_url="http://beacon-node-a:1234",
            spec=spec,
            scheduler=scheduler,
            task_manager=task_manager,
        )
        if spec_mismatch:
            with pytest.raises(
                ValueError,
                match="Spec values returned by beacon node beacon-node-a not equal to hardcoded spec values",
            ):
                await bn._initialize_full()
        else:
            await bn._initialize_full()
