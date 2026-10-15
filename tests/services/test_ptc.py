import asyncio

import pytest

from providers import BeaconChain, Vero
from schemas import SchemaBeaconAPI
from schemas.beacon_api import ValidatorStatus
from schemas.shared import ForkVersion
from schemas.validator import ValidatorIndexPubkey
from services import PtcService


async def test_update_duties(ptc_service: PtcService) -> None:
    # This test just checks that no exception is thrown
    assert len(ptc_service.ptc_duties) == 0
    await ptc_service._update_duties()
    assert len(ptc_service.ptc_duties) > 0


@pytest.mark.parametrize(
    "fork_version",
    [
        pytest.param(ForkVersion.ELECTRA, id="Electra"),
        pytest.param(ForkVersion.FULU, id="Fulu"),
        pytest.param(ForkVersion.GLOAS, id="Gloas"),
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    "enable_keymanager_api",
    [
        pytest.param(False, id="signature_provider: RemoteSigner"),
        pytest.param(True, id="signature_provider: Keymanager"),
    ],
    indirect=True,
)
async def test_attest_if_not_yet_attested(
    ptc_service: PtcService,
    beacon_chain: BeaconChain,
    validators: list[ValidatorIndexPubkey],
    fork_version: ForkVersion,
    enable_keymanager_api: bool,
    vero: Vero,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Populate the service with a PTC duty
    duty_slot = beacon_chain.current_slot + 1
    duty_epoch = duty_slot // beacon_chain.SLOTS_PER_EPOCH

    first_active_validator = next(
        v for v in validators if v.status == ValidatorStatus.ACTIVE_ONGOING
    )
    ptc_service.ptc_duties[duty_epoch].add(
        SchemaBeaconAPI.PtcDuty(
            pubkey=first_active_validator.pubkey,
            validator_index=str(first_active_validator.index),
            slot=str(duty_slot),
        ),
    )

    ptc_service._last_slot_duty_started_for = 0
    ptc_service._last_slot_duty_completed_for = 0

    atts_published_before = vero.metrics.vc_published_ptc_attestations_c._value.get()

    # Wait for slot to start
    await asyncio.sleep(max(0.0, -beacon_chain.time_since_slot_start(duty_slot)))
    await ptc_service.attest_if_not_yet_attested(slot=duty_slot)

    assert any("Published PTC attestations" in m for m in caplog.messages)
    assert (
        vero.metrics.vc_published_ptc_attestations_c._value.get()
        == atts_published_before + 1
    )
    assert ptc_service._last_slot_duty_started_for == duty_slot
    assert ptc_service._last_slot_duty_completed_for == duty_slot


@pytest.mark.parametrize(
    argnames="slot_offset",
    argvalues=[pytest.param(10, id="future slot"), pytest.param(-10, id="past slot")],
)
async def test_attest_to_invalid_slot(
    slot_offset: int,
    ptc_service: PtcService,
    beacon_chain: BeaconChain,
    vero: Vero,
    caplog: pytest.LogCaptureFixture,
) -> None:
    atts_published_before = vero.metrics.vc_published_ptc_attestations_c._value.get()
    with pytest.raises(RuntimeError, match="Invalid slot for PTC attestation: "):
        await ptc_service.attest_if_not_yet_attested(
            slot=beacon_chain.current_slot + slot_offset
        )

    assert (
        vero.metrics.vc_published_ptc_attestations_c._value.get()
        == atts_published_before
    )
