from enum import Enum

import msgspec


class RemoteKey(msgspec.Struct):
    pubkey: str
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
    pubkeys: list[str]


class DeleteStatus(Enum):
    DELETED = "deleted"
    NOT_FOUND = "not_found"
    ERROR = "error"


class DeleteStatusMessage(msgspec.Struct):
    status: DeleteStatus
    message: str


class DeleteRemoteKeysResponse(msgspec.Struct):
    data: list[DeleteStatusMessage]
