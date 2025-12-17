import math
import sys
from enum import Enum

from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    start_http_server,
)

from spec.base import SpecFulu
from spec.constants import INTERVALS_PER_SLOT

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


def _setup_head_event_time_metric(
    seconds_per_slot: int,
    attestation_deadline: float,
    step_fine: float = 0.25,  # 250 ms
    step_coarse: float = 1.0,  #   1 s
) -> Histogram:
    """
    For tracking at which point into the slot a head event was received
    from each connected beacon node.

    Histogram buckets are divided into:
    *  Fine resolution (step_fine) until `attestation_deadline`
    *  Coarse resolution (step_coarse) for the rest of the slot
    """

    # Every multiple of step_fine that is <= attestation_deadline
    k_max = int(attestation_deadline / step_fine)
    fine_buckets = [round(step_fine * k, 2) for k in range(1, k_max + 1)]

    # Add the exact deadline edge if it is not already present
    if round(attestation_deadline, 2) not in fine_buckets:
        fine_buckets.append(round(attestation_deadline, 2))

    # First coarse edge after the deadline
    first_coarse = math.ceil(attestation_deadline / step_coarse) * step_coarse
    if first_coarse in fine_buckets:
        first_coarse += step_coarse

    n_coarse = math.ceil((seconds_per_slot - first_coarse) / step_coarse) + 1
    coarse_buckets = [round(first_coarse + step_coarse * k, 2) for k in range(n_coarse)]

    return Histogram(
        "head_event_time",
        "Time into slot at which a head event for the slot was received",
        labelnames=["host"],
        buckets=fine_buckets + coarse_buckets,
    )


def _setup_duty_time_metrics(
    seconds_per_slot: int,
) -> tuple[Histogram, Histogram]:
    buckets = [
        item
        for sublist in [
            [i, i + 0.25, i + 0.5, i + 0.75] for i in range(seconds_per_slot)
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
            seconds_per_slot=int(spec.SECONDS_PER_SLOT),
            attestation_deadline=int(spec.SECONDS_PER_SLOT) / INTERVALS_PER_SLOT,
        )

        # ValidatorDutyService
        self.duty_start_time_h, self.duty_submission_time_h = _setup_duty_time_metrics(
            seconds_per_slot=int(spec.SECONDS_PER_SLOT)
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
