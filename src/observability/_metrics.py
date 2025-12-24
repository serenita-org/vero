import sys
from enum import Enum

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)

from spec.base import SpecFulu
from spec.common import get_slot_component_duration_ms

from ._vero_info import get_service_commit, get_service_version


class ErrorType(Enum):
    ATTESTATION_CONSENSUS = "attestation-consensus"
    ATTESTATION_PUBLISH = "attestation-publish"
    AGGREGATE_ATTESTATION_PRODUCE = "aggregate-attestation-produce"
    AGGREGATE_ATTESTATION_PUBLISH = "aggregate-attestation-publish"
    BLOCK_PRODUCE = "block-produce"
    BLOCK_PUBLISH = "block-publish"
    SYNC_COMMITTEE_CONTRIBUTION_PRODUCE = "sync-committee-contribution-produce"
    SYNC_COMMITTEE_CONTRIBUTION_PUBLISH = "sync-committee-contribution-publish"
    SYNC_COMMITTEE_MESSAGE_PRODUCE = "sync-committee-message-produce"
    SYNC_COMMITTEE_MESSAGE_PUBLISH = "sync-committee-message-publish"
    DUTIES_UPDATE = "duties-update"
    VALIDATOR_STATUS_UPDATE = "validator-status-update"
    SIGNATURE = "signature"
    EVENT_CONSUMER = "event-consumer"
    OTHER = "other"


class HandledRuntimeError(Exception):
    def __init__(self, errors_counter: Counter, error_type: ErrorType) -> None:
        errors_counter.labels(error_type=error_type.value).inc()


def _setup_head_event_time_metric(
    slot_duration_ms: int,
    attestation_due_ms: int,
    step_fine_ms: int = 250,
    step_coarse_ms: int = 1_000,
) -> Histogram:
    """
    Tracks time into slot (seconds) at which a head event was received.

    Buckets:
      - fine (step_fine_ms) up to attestation_due_ms (inclusive)
      - coarse (step_coarse_ms) after that, until slot_duration_ms (inclusive)
    """
    buckets_ms: list[int] = []

    # Fine buckets: step_fine_ms, 2*step_fine_ms, ... <= attestation_due_ms
    k_max = attestation_due_ms // step_fine_ms
    buckets_ms.extend(step_fine_ms * k for k in range(1, k_max + 1))

    # Coarse buckets start: first multiple of step_coarse_ms after due time
    first_coarse_ms = ((attestation_due_ms // step_coarse_ms) + 1) * step_coarse_ms

    # Add exact deadline edge if not already present.
    # Skip adding the exact deadline if it is extremely close (<=1ms) to the
    # first coarse bucket.
    # The skipping is needed in practice due to the attestation deadline being
    # 3999ms with 12s slot times because of integer division
    # in `get_slot_component_duration_ms`. That in turn results in buckets
    # of 3999 and 4000 which we don't want, they'd contain practically identical
    # values.
    if (
        buckets_ms
        and buckets_ms[-1] != attestation_due_ms
        and first_coarse_ms - attestation_due_ms > 1
    ):
        buckets_ms.append(attestation_due_ms)

    # Add coarse edges: first_coarse_ms, first_coarse_ms + step_coarse_ms, ... <= slot_duration_ms
    t = first_coarse_ms
    while t <= slot_duration_ms:
        # Only append if it increases (protects against overlaps)
        if t > buckets_ms[-1]:
            buckets_ms.append(t)
        t += step_coarse_ms

    # Ensure the exact slot end is present
    if buckets_ms[-1] != slot_duration_ms:
        buckets_ms.append(slot_duration_ms)

    buckets_s = [ms / 1000.0 for ms in buckets_ms]

    return Histogram(
        "head_event_time",
        "Time into slot at which a head event for the slot was received",
        labelnames=["host"],
        buckets=buckets_s,
    )


def _setup_duty_time_metrics(
    slot_duration_ms: int,
) -> tuple[Histogram, Histogram]:
    buckets = [
        item
        for sublist in [
            [i, i + 0.25, i + 0.5, i + 0.75] for i in range(slot_duration_ms // 1_000)
        ]
        for item in sublist
    ]
    buckets.remove(0)

    duty_start_time = Histogram(
        "duty_start_time",
        "Time into slot at which a duty starts",
        labelnames=["duty"],
        buckets=buckets,
    )

    duty_submission_time = Histogram(
        "duty_submission_time",
        "Time into slot at which a duty submission starts",
        labelnames=["duty"],
        buckets=buckets,
    )

    return duty_start_time, duty_submission_time


class Metrics:
    def __init__(
        self,
        spec: SpecFulu,
        addr: str,
        port: int,
    ) -> None:
        if "pytest" not in sys.modules:
            # do not start the HTTP server while running tests
            start_http_server(addr=addr, port=port)

        self.errors_c = Counter(
            "errors",
            "Number of errors",
            labelnames=["error_type"],
        )
        for enum_type in ErrorType:
            self.errors_c.labels(enum_type.value).reset()

        self.vero_info_g = Gauge(
            "vero_info",
            "Information about the Vero build.",
            labelnames=["commit", "version"],
        )
        self.vero_info_g.labels(
            commit=get_service_commit(),
            version=get_service_version(),
        ).set(1)

        # Event loop related
        self.event_loop_lag_h = Histogram(
            "event_loop_lag_seconds",
            "Estimate of event loop lag",
            labelnames=["time_since_slot_start"],
        )
        self.event_loop_tasks_g = Gauge(
            "event_loop_tasks",
            "Number of tasks in event loop",
        )

        # EventConsumerService
        self.vc_processed_beacon_node_events_c = Counter(
            "vc_processed_beacon_node_events",
            "Successfully processed beacon node events",
            labelnames=["host", "event_type"],
        )
        self.head_event_time_h = _setup_head_event_time_metric(
            slot_duration_ms=int(spec.SLOT_DURATION_MS),
            attestation_due_ms=get_slot_component_duration_ms(
                basis_points=spec.ATTESTATION_DUE_BPS,
                slot_duration_ms=spec.SLOT_DURATION_MS,
            ),
        )

        # ValidatorDutyService
        self.duty_start_time_h, self.duty_submission_time_h = _setup_duty_time_metrics(
            slot_duration_ms=int(spec.SLOT_DURATION_MS)
        )

        # AttestationService
        self.vc_published_attestations_c = Counter(
            "vc_published_attestations",
            "Successfully published attestations",
        )
        self.vc_published_attestations_c.reset()
        self.vc_published_aggregate_attestations_c = Counter(
            "vc_published_aggregate_attestations",
            "Successfully published aggregate attestations",
        )
        self.vc_published_aggregate_attestations_c.reset()
        self.vc_attestation_consensus_time_h = Histogram(
            "vc_attestation_consensus_time",
            "Time it took to achieve consensus on the attestation beacon block root",
            buckets=[
                0.025,
                0.05,
                0.075,
                0.1,
                0.15,
                0.2,
                0.25,
                0.3,
                0.4,
                0.5,
                0.75,
                1,
                2,
                3,
            ],
        )
        self.vc_attestation_consensus_failures_c = Counter(
            "vc_attestation_consensus_failures",
            "Number of attestation consensus failures",
        )
        self.vc_attestation_consensus_failures_c.reset()

        # BlockProposalService
        self.vc_published_blocks_c = Counter(
            "vc_published_blocks",
            "Successfully published blocks",
        )
        self.vc_published_blocks_c.reset()

        # SyncCommitteeService
        self.vc_published_sync_committee_messages_c = Counter(
            "vc_published_sync_committee_messages",
            "Successfully published sync committee messages",
        )
        self.vc_published_sync_committee_messages_c.reset()
        self.vc_published_sync_committee_contributions_c = Counter(
            "vc_published_sync_committee_contributions",
            "Successfully published sync committee contributions",
        )
        self.vc_published_sync_committee_contributions_c.reset()

        # ValidatorStatusTrackerService
        self.validator_status_g = Gauge(
            "validator_status",
            "Number of validators per status",
            labelnames=["status"],
        )
        self.slashing_detected_g = Gauge(
            "slashing_detected",
            "1 if any of the connected validators have been slashed, 0 otherwise",
        )
        self.slashing_detected_g.set(0)

        # BeaconNode
        self.beacon_node_score_g = Gauge(
            "beacon_node_score",
            "Beacon node score",
            labelnames=["host"],
        )
        self.beacon_node_version_g = Gauge(
            "beacon_node_version",
            "Beacon node version",
            labelnames=["host", "version"],
        )
        self.beacon_node_aggregate_attestation_participant_count_h = Histogram(
            "beacon_node_aggregate_attestation_participant_count",
            "Tracks the number of participants included in aggregates returned by this beacon node.",
            labelnames=["host"],
            buckets=[16, 32, 64, 128, 256, 512, 1_024, 2_048],
        )
        self.beacon_node_sync_contribution_participant_count_h = Histogram(
            "beacon_node_sync_contribution_participant_count",
            "Tracks the number of participants included in sync contributions returned by this beacon node.",
            labelnames=["host"],
            buckets=[8, 16, 32, 64, 128],
        )
        _block_value_buckets = [
            int(0.001 * 1e18),
            int(0.01 * 1e18),
            int(0.1 * 1e18),
            int(1 * 1e18),
            int(10 * 1e18),
        ]
        self.beacon_node_consensus_block_value_h = Histogram(
            "beacon_node_consensus_block_value",
            "Tracks the value of consensus layer rewards paid to the proposer in the block produced by this beacon node",
            labelnames=["host"],
            buckets=_block_value_buckets,
        )
        self.beacon_node_execution_payload_value_h = Histogram(
            "beacon_node_execution_payload_value",
            "Tracks the value of execution payloads in blocks produced by this beacon node",
            labelnames=["host"],
            buckets=_block_value_buckets,
        )
        self.checkpoint_confirmations_c = Counter(
            "checkpoint_confirmations",
            "Tracks how many times each beacon node confirmed finality checkpoints.",
            labelnames=["host"],
        )

        # RemoteSigner
        self.signed_messages_c = Counter(
            "signed_messages",
            "Number of signed messages",
            labelnames=["signable_message_type"],
        )
        self.remote_signer_score_g = Gauge(
            "remote_signer_score",
            "Remote signer score",
            labelnames=["host"],
        )
