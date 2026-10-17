from enum import Enum
from typing import Annotated

import msgspec

PUBKEY_PATTERN = "^0x[a-fA-F0-9]{96}$"
Pubkey = Annotated[str, msgspec.Meta(pattern=PUBKEY_PATTERN)]
EthAddress = Annotated[str, msgspec.Meta(pattern="^0x[a-fA-F0-9]{40}$")]
UInt64String = Annotated[str, msgspec.Meta(pattern="^(0|[1-9][0-9]{0,19})$")]
BLSSignature = Annotated[str, msgspec.Meta(pattern="^0x[a-fA-F0-9]{192}$")]


class ErrorResponse(msgspec.Struct):
    message: str


class RemoteKey(msgspec.Struct):
    pubkey: Pubkey
    url: str


class RemoteKeyWithReadOnlyStatus(RemoteKey):
    readonly: bool


class ListRemoteKeysResponse(msgspec.Struct):
    data: list[RemoteKeyWithReadOnlyStatus]


class ImportRemoteKeysRequest(msgspec.Struct):
    remote_keys: list[RemoteKey]


class ImportStatus(Enum):
    IMPORTED = "imported"
    DUPLICATE = "duplicate"
    ERROR = "error"


class ImportStatusMessage(msgspec.Struct):
    status: ImportStatus
    message: str


class ImportRemoteKeysResponse(msgspec.Struct):
    data: list[ImportStatusMessage]


class DeleteRemoteKeysRequest(msgspec.Struct):
    pubkeys: list[Pubkey]


class DeleteStatus(Enum):
    DELETED = "deleted"
    NOT_FOUND = "not_found"
    ERROR = "error"


class DeleteStatusMessage(msgspec.Struct):
    status: DeleteStatus
    message: str


class DeleteRemoteKeysResponse(msgspec.Struct):
    data: list[DeleteStatusMessage]


# Fee recipient endpoints
class ValidatorFeeRecipient(msgspec.Struct):
    pubkey: Pubkey
    ethaddress: EthAddress


class ListFeeRecipientResponse(msgspec.Struct):
    data: ValidatorFeeRecipient


class SetFeeRecipientRequest(msgspec.Struct):
    ethaddress: EthAddress


# Gas limit endpoints
class ValidatorGasLimit(msgspec.Struct):
    pubkey: Pubkey
    gas_limit: UInt64String


class ListGasLimitResponse(msgspec.Struct):
    data: ValidatorGasLimit


class SetGasLimitRequest(msgspec.Struct):
    gas_limit: UInt64String


# Builder configuration endpoints
class BuilderEntry(msgspec.Struct, omit_defaults=True):
    url: Annotated[str, msgspec.Meta(min_length=1, max_length=2048)]
    auth_data: (
        Annotated[str, msgspec.Meta(pattern="^0x(?:[a-fA-F0-9]{2}){1,4096}$")]
        | msgspec.UnsetType
    ) = msgspec.UNSET
    builder_pubkeys: (
        Annotated[list[Pubkey], msgspec.Meta(max_length=64)] | msgspec.UnsetType
    ) = msgspec.UNSET
    max_execution_payment: UInt64String | msgspec.UnsetType = msgspec.UNSET
    min_bid: UInt64String | msgspec.UnsetType = msgspec.UNSET
    builder_boost_factor: UInt64String | msgspec.UnsetType = msgspec.UNSET


class BuilderConfig(msgspec.Struct, omit_defaults=True):
    min_bid: UInt64String | msgspec.UnsetType = msgspec.UNSET
    builder_boost_factor: UInt64String | msgspec.UnsetType = msgspec.UNSET
    builders: (
        Annotated[list[BuilderEntry], msgspec.Meta(max_length=64)] | msgspec.UnsetType
    ) = msgspec.UNSET


class ResolvedBuilderEntry(msgspec.Struct):
    url: str
    auth_data: str
    builder_pubkeys: list[Pubkey]
    max_execution_payment: UInt64String
    min_bid: UInt64String
    builder_boost_factor: UInt64String


class ResolvedBuilderConfig(msgspec.Struct):
    min_bid: UInt64String
    builder_boost_factor: UInt64String
    builders: list[ResolvedBuilderEntry]


class GetBuilderConfigResponse(msgspec.Struct):
    data: ResolvedBuilderConfig


# Graffiti endpoints
class ValidatorGraffiti(msgspec.Struct):
    pubkey: Pubkey
    graffiti: str


class GraffitiResponse(msgspec.Struct):
    data: ValidatorGraffiti


class SetGraffitiRequest(msgspec.Struct):
    graffiti: str


class VoluntaryExit(msgspec.Struct):
    epoch: UInt64String
    validator_index: UInt64String


class SignedVoluntaryExit(msgspec.Struct):
    message: VoluntaryExit
    signature: BLSSignature


class SignVoluntaryExitResponse(msgspec.Struct):
    data: SignedVoluntaryExit
