from enum import Enum

import msgspec


class ForkVersion(Enum):
    ELECTRA = "electra"
    FULU = "fulu"
    GLOAS = "gloas"


class ExecutionPayloadBid(msgspec.Struct):
    parent_block_hash: str
    parent_block_root: str
    block_hash: str
    prev_randao: str
    fee_recipient: str
    gas_limit: str
    builder_index: str
    slot: str
    value: str
    execution_payment: str
    blob_kzg_commitments: list[str]
    execution_requests_root: str


class SignedExecutionPayloadBid(msgspec.Struct):
    message: ExecutionPayloadBid
    signature: str
