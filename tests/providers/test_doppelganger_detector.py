import re
from contextlib import AbstractContextManager
from contextlib import nullcontext as does_not_raise

import msgspec.json
import pytest
from _pytest.raises import RaisesExc
from aiohttp import ClientConnectionError
from aioresponses import aioresponses

from providers import BeaconNode, DoppelgangerDetector, Vero
from providers.doppelganger_detector import DoppelgangersDetected


@pytest.mark.parametrize(
    argnames=("live_indices", "expectation"),
    argvalues=[
        pytest.param(
            {},
            does_not_raise(),
            id="no doppelgangers",
        ),
        pytest.param(
            {1},
            pytest.raises(DoppelgangersDetected),
            id="single doppelganger detected",
        ),
        pytest.param(
            {1, 2, 3},
            pytest.raises(DoppelgangersDetected),
            id="multiple doppelgangers detected",
        ),
    ],
)
def test_process_liveness_data(
    live_indices: set[int],
    expectation: AbstractContextManager[
        RaisesExc[DoppelgangersDetected] | does_not_raise[None]
    ],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with expectation:
        DoppelgangerDetector(
            beacon_chain=None,  # type: ignore[arg-type]
            beacon_nodes=None,  # type: ignore[arg-type]
            validator_status_tracker_service=None,  # type: ignore[arg-type]
        )._process_liveness_data(
            live_indices=live_indices,
        )

    log_record = next(iter(caplog.records))
    if isinstance(expectation, RaisesExc):
        assert log_record.levelname == "CRITICAL"
        assert "Doppelgangers detected" in log_record.message
    else:
        assert "No doppelgangers detected across beacon nodes" in log_record.message


@pytest.mark.parametrize(
    argnames=("bn_reachable", "response_data", "expectation", "expected_return_value"),
    argvalues=[
        pytest.param(
            True,
            msgspec.json.encode({"data": [{"index": "1", "is_live": True}]}),
            does_not_raise(),
            {1},
            id="happy case - bn reachable and returns expected data",
        ),
        pytest.param(
            True,
            b"bad_data",
            pytest.raises(
                msgspec.DecodeError,
                match="JSON is malformed",
            ),
            None,
            id="invalid response data",
        ),
        pytest.param(
            False,
            b"",
            pytest.raises(
                ClientConnectionError,
                match="Connection refused: POST http://beacon-node-a:1234/eth/v1/validator/liveness/123",
            ),
            None,
            id="bn not reachable",
        ),
    ],
)
async def test_fetch_liveness_data(
    bn_reachable: bool,
    response_data: bytes,
    expectation: AbstractContextManager[RaisesExc[RuntimeError] | does_not_raise[None]],
    expected_return_value: set[int] | None,
    vero: Vero,
    caplog: pytest.LogCaptureFixture,
) -> None:
    detector = DoppelgangerDetector(
        beacon_chain=None,  # type: ignore[arg-type]
        beacon_nodes=[
            BeaconNode(
                base_url="http://beacon-node-a:1234",
                vero=vero,
            )
        ],
        validator_status_tracker_service=None,  # type: ignore[arg-type]
    )

    with aioresponses() as m:
        if bn_reachable:
            m.post(
                url=re.compile(
                    r"http://beacon-node-a:1234/eth/v1/validator/liveness/\d+"
                ),
                body=response_data,
            )

        with expectation:
            return_value = await detector._fetch_liveness_data(
                epoch=123,
                validator_indices=[1, 2, 3],
            )
            assert expected_return_value == return_value
