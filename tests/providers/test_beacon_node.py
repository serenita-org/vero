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
@pytest.mark.parametrize(
    argnames="cli_args",
    argvalues=[
        pytest.param(
            {
                "ignore_spec_mismatch": False,
            },
            id="spec mismatch not ignored",
        ),
        pytest.param(
            {
                "ignore_spec_mismatch": True,
            },
            id="spec mismatch ignored",
        ),
    ],
    indirect=["cli_args"],
)
async def test_initialize_spec_mismatch(
    spec_mismatch: bool,
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
            url=re.compile(r"http://beacon-node-\w:1234/eth/v1/config/spec"),
            callback=lambda *args, **kwargs: CallbackResult(
                payload=dict(data=spec_to_return.to_obj()),
            ),
        )

        bn = BeaconNode(
            base_url="http://beacon-node-a:1234",
            vero=vero,
        )
        if not spec_mismatch or vero.cli_args.ignore_spec_mismatch:
            # No mismatch, or mismatch explicitly ignored -> init should not raise
            await bn._initialize_full()
            assert bn.initialized is True
        else:
            with pytest.raises(
                ValueError,
                match=re.escape(
                    "Spec values returned by beacon node beacon-node-a not equal to hardcoded spec values. Use the `--ignore-spec-mismatch` flag to ignore this error."
                ),
            ):
                await bn._initialize_full()

        await bn.client_session.close()


@pytest.mark.parametrize(
    "cli_args",
    [
        pytest.param({"ignore_spec_mismatch": False}, id="strict"),
        pytest.param({"ignore_spec_mismatch": True}, id="ignored"),
    ],
    indirect=True,
)
async def test_initialize_unparseable_spec(vero: Vero) -> None:
    """Spec parsing errors should only prevent initialization in strict mode."""
    spec_data = vero.spec.to_obj()
    spec_data["SLOTS_PER_EPOCH"] = "invalid"

    bn = BeaconNode(base_url="http://beacon-node-a:1234", vero=vero)
    try:
        with aioresponses() as m:
            m.get(
                "http://beacon-node-a:1234/eth/v1/config/spec",
                payload=dict(data=spec_data),
            )

            if vero.cli_args.ignore_spec_mismatch:
                await bn._initialize_full()
                assert bn.initialized is True
                assert bn.spec is vero.spec
            else:
                with pytest.raises(ValueError, match="invalid"):
                    await bn._initialize_full()
                assert bn.initialized is False
    finally:
        await bn.client_session.close()
