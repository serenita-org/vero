import pytest

from schemas import SchemaBeaconAPI, SchemaShared
from schemas.beacon_api import is_optimistic


@pytest.mark.parametrize("optimistic", [True, False])
def test_is_optimistic(optimistic: bool) -> None:
    response = SchemaBeaconAPI.ExecutionOptimisticResponse(
        execution_optimistic=optimistic
    )
    reorg = SchemaBeaconAPI.ChainReorgEvent(
        execution_optimistic=optimistic,
        slot="1",
        depth="1",
        old_head_block="0xold",
        new_head_block="0xnew",
    )
    head = SchemaBeaconAPI.HeadV2Event(
        version=SchemaShared.ForkVersion.GLOAS,
        data=SchemaBeaconAPI.HeadV2EventData(
            slot="1",
            block="0xblock",
            state="0xstate",
            payload_status="full",
            epoch_transition=False,
            current_epoch_dependent_root="0xcurrent",
            next_epoch_dependent_root="0xnext",
            execution_optimistic=optimistic,
        ),
    )

    assert is_optimistic(response) is optimistic
    assert is_optimistic(reorg) is optimistic
    assert is_optimistic(head) is optimistic


def test_event_without_optimistic_status() -> None:
    event = SchemaBeaconAPI.ExecutionPayloadAvailableEvent(
        slot="1", block_root="0xblock"
    )
    assert is_optimistic(event) is False
