from enum import Enum

from prometheus_client import Counter


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


ERRORS_METRIC = Counter(
    "errors",
    "Number of errors",
    labelnames=["error_type"],
)
for enum_type in ErrorType:
    ERRORS_METRIC.labels(enum_type.value).reset()
