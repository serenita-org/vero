"""API response models for the Builder API.

Useful links:

https://github.com/ethereum/builder-specs
https://ethereum.github.io/builder-specs/
"""

import msgspec

from .shared import ForkVersion, SignedExecutionPayloadBid


class GetExecutionPayloadBidResponse(msgspec.Struct):
    version: ForkVersion
    data: SignedExecutionPayloadBid
