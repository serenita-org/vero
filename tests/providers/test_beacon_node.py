import contextlib
import re
from copy import copy

import pytest
from aioresponses import CallbackResult, aioresponses

from providers import BeaconNode, Vero
from spec.base import Version
from spec.common import UInt64SerializedAsString


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
    vero: Vero,
) -> None:
    """The BeaconNode should fail to initialize on a spec mismatch."""
    with contextlib.ExitStack() as stack:
        m = stack.enter_context(aioresponses())

        spec_to_return = vero.spec
        if spec_mismatch:
            spec_to_return = copy(vero.spec)
            spec_to_return.SLOTS_PER_EPOCH = UInt64SerializedAsString(5)
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
            vero=vero,
        )
        if spec_mismatch:
            with pytest.raises(
                ValueError,
                match="Spec values returned by beacon node beacon-node-a not equal to hardcoded spec values",
            ):
                await bn._initialize_full()
        else:
            await bn._initialize_full()
