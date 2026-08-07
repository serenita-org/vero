"""API response models for the Builder API.

Useful links:

https://github.com/ethereum/builder-specs
https://ethereum.github.io/builder-specs/
"""
import msgspec

from .beacon_api import ForkVersion

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

class GetExecutionPayloadBidResponse(msgspec.Struct):
    version: ForkVersion
    data: SignedExecutionPayloadBid
