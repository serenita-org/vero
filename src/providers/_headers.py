from enum import Enum


class ContentType(Enum):
    JSON = "application/json"
    MSGPACK = "application/vnd.msgpack"
    OCTET_STREAM = "application/octet-stream"
    TEXT_PLAIN = "text/plain"


ETH_CONSENSUS_VERSION = "Eth-Consensus-Version"
ETH_CONSENSUS_BLOCK_VALUE = "Eth-Consensus-Block-Value"

ETH_EXECUTION_PAYLOAD_VALUE = "Eth-Execution-Payload-Value"
ETH_EXECUTION_PAYLOAD_BLINDED = "Eth-Execution-Payload-Blinded"
ETH_EXECUTION_PAYLOAD_INCLUDED = "Eth-Execution-Payload-Included"
ETH_BUILDER_URL = "Eth-Builder-Url"
ETH_BLOB_DATA_INCLUDED = "Eth-Blob-Data-Included"

# Builder API
DATE_MILLISECONDS = "Date-Milliseconds"
X_TIMEOUT_MS = "X-Timeout-Ms"
