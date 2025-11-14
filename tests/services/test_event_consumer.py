import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from providers import BeaconChain, BeaconNode, MultiBeaconNode, Vero
from schemas import SchemaBeaconAPI
from services import EventConsumerService
from tasks import TaskManager


@pytest.fixture
def event_consumer(
    multi_beacon_node: MultiBeaconNode,
    beacon_chain: BeaconChain,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
) -> EventConsumerService:
    return EventConsumerService(
        beacon_nodes=multi_beacon_node.beacon_nodes,
        beacon_chain=beacon_chain,
        scheduler=scheduler,
        task_manager=task_manager,
    )


@pytest.mark.parametrize(
    argnames=("event", "expected_log_messages"),
    argvalues=[
        pytest.param(
            SchemaBeaconAPI.HeadEvent(
                execution_optimistic=False,
                slot="10000",
                block="0xblockroot",
                previous_duty_dependent_root="0xprevious",
                current_duty_dependent_root="0xcurrent",
            ),
            ["[bn-test] New head @ 10000 : 0xblockroot"],
            id="HeadEvent",
        ),
        pytest.param(
            SchemaBeaconAPI.HeadEvent(
                execution_optimistic=False,
                slot="100",
                block="0xblockroot",
                previous_duty_dependent_root="0xprevious",
                current_duty_dependent_root="0xcurrent",
            ),
            ["Ignoring event for old slot 100 from bn-test."],
            id="HeadEvent - old slot",
        ),
        pytest.param(
            SchemaBeaconAPI.ChainReorgEvent(
                execution_optimistic=False,
                slot="10000",
                depth="2",
                old_head_block="0xoldhead",
                new_head_block="0xnewhead",
            ),
            [
                "Chain reorg of depth 2 at slot 10000, old head 0xoldhead, new head 0xnewhead"
            ],
            id="ChainReorgEvent",
        ),
        pytest.param(
            SchemaBeaconAPI.AttesterSlashingEvent(
                attestation_1=SchemaBeaconAPI.AttesterSlashingEventAttestation(
                    attesting_indices=["1", "2", "3"]
                ),
                attestation_2=SchemaBeaconAPI.AttesterSlashingEventAttestation(
                    attesting_indices=["2", "4", "5"]
                ),
            ),
            ["AttesterSlashingEvent: {'2'}"],
            id="AttesterSlashingEvent",
        ),
        pytest.param(
            SchemaBeaconAPI.ProposerSlashingEvent(
                signed_header_1=SchemaBeaconAPI.ProposerSlashingEventData(
                    message=SchemaBeaconAPI.ProposerSlashingEventMessage(
                        proposer_index="1234"
                    )
                ),
                signed_header_2=SchemaBeaconAPI.ProposerSlashingEventData(
                    message=SchemaBeaconAPI.ProposerSlashingEventMessage(
                        proposer_index="1234"
                    )
                ),
            ),
            ["ProposerSlashingEvent: 1234"],
            id="ProposerSlashingEvent",
        ),
    ],
)
@pytest.mark.usefixtures("_unregister_prometheus_metrics")
async def test_handle_event(
    event: SchemaBeaconAPI.BeaconNodeEvent,
    expected_log_messages: list[str],
    event_consumer: EventConsumerService,
    vero: Vero,
    caplog: pytest.LogCaptureFixture,
) -> None:
    event_consumer._handle_event(
        event=event,
        beacon_node=BeaconNode(
            base_url="http://bn-test",
            vero=vero,
        ),
    )

    for log_message in expected_log_messages:
        assert any(log_message in m for m in caplog.messages)


@pytest.mark.usefixtures("_unregister_prometheus_metrics")
async def test_recent_event_keys(
    event_consumer: EventConsumerService,
    vero: Vero,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for i in range(100):
        event_consumer._handle_event(
            event=SchemaBeaconAPI.HeadEvent(
                execution_optimistic=False,
                slot=str(event_consumer.beacon_chain.current_slot + i),
                block=f"0xblock-{i}",
                previous_duty_dependent_root="0xprevious",
                current_duty_dependent_root="0xcurrent",
            ),
            beacon_node=BeaconNode(
                base_url="http://bn-test",
                vero=vero,
            ),
        )

    # The last 10 event keys should be cached
    assert len(event_consumer._recent_event_keys) == 10
    assert list(event_consumer._recent_event_keys) == [
        f"0xblock-{i}" for i in range(90, 100)
    ]
