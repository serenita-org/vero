from contextlib import AbstractContextManager
from contextlib import nullcontext as does_not_raise

import pytest
from _pytest.python_api import RaisesContext

from providers import DoppelgangerDetector
from providers.doppelganger_detector import DoppelgangersDetected
from schemas import SchemaBeaconAPI


@pytest.mark.parametrize(
    argnames=("liveness_data", "expectation"),
    argvalues=[
        pytest.param(
            [
                SchemaBeaconAPI.ValidatorLiveness(index="1", is_live=False),
                SchemaBeaconAPI.ValidatorLiveness(index="2", is_live=False),
                SchemaBeaconAPI.ValidatorLiveness(index="3", is_live=False),
            ],
            does_not_raise(),
            id="no doppelgangers",
        ),
        pytest.param(
            [
                SchemaBeaconAPI.ValidatorLiveness(index="1", is_live=True),
                SchemaBeaconAPI.ValidatorLiveness(index="2", is_live=False),
                SchemaBeaconAPI.ValidatorLiveness(index="3", is_live=False),
            ],
            pytest.raises(DoppelgangersDetected),
            id="doppelganger detected",
        ),
        pytest.param(
            [
                SchemaBeaconAPI.ValidatorLiveness(index="1", is_live=True),
                SchemaBeaconAPI.ValidatorLiveness(index="2", is_live=True),
                SchemaBeaconAPI.ValidatorLiveness(index="3", is_live=True),
            ],
            pytest.raises(DoppelgangersDetected),
            id="multiple doppelgangers detected",
        ),
    ],
)
def test_process_liveness_data(
    liveness_data: list[SchemaBeaconAPI.ValidatorLiveness],
    expectation: AbstractContextManager[
        RaisesContext[DoppelgangersDetected] | does_not_raise[None]
    ],
    caplog: pytest.LogCaptureFixture,
) -> None:
    with expectation:
        DoppelgangerDetector(
            beacon_chain=None,  # type: ignore[arg-type]
            beacon_node=None,  # type: ignore[arg-type]
            validator_status_tracker_service=None,  # type: ignore[arg-type]
        )._process_liveness_data(
            liveness_data=liveness_data,
        )

    log_record = next(iter(caplog.records))
    if isinstance(expectation, RaisesContext):
        assert log_record.levelname == "CRITICAL"
        assert "Doppelgangers detected" in log_record.message
    else:
        assert "No doppelgangers detected" in log_record.message
