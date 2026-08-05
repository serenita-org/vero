from enum import Enum


class ContentType(Enum):
    JSON = "application/json"
    MSGPACK = "application/vnd.msgpack"
    OCTET_STREAM = "application/octet-stream"
    TEXT_PLAIN = "text/plain"


ETH_CONSENSUS_VERSION = "Eth-Consensus-Version"
