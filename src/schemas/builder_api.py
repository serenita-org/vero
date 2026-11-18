"""API response models for the Builder API.

Useful links:

https://github.com/ethereum/builder-specs
https://ethereum.github.io/builder-specs/
"""

import msgspec

from .shared import Fork, SignedBuilderRequestAuth, SignedExecutionPayloadBid


class BuilderPreferences(msgspec.Struct):
    max_execution_payment: str


class BuilderPreferencesRequest(msgspec.Struct):
    preferences: BuilderPreferences
    auth: SignedBuilderRequestAuth


class GetExecutionPayloadBidResponse(msgspec.Struct):
    version: Fork
    data: SignedExecutionPayloadBid
