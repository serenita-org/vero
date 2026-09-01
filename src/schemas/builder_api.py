"""API response models for the Builder API.

Useful links:

https://github.com/ethereum/builder-specs
https://ethereum.github.io/builder-specs/
"""

import msgspec

from .shared import BuilderRequestAuth, ForkVersion, SignedExecutionPayloadBid


class SignedBuilderRequestAuth(msgspec.Struct):
    message: BuilderRequestAuth
    signature: str


class GetExecutionPayloadBidResponse(msgspec.Struct):
    version: ForkVersion
    data: SignedExecutionPayloadBid
