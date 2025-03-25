import asyncio
import logging
import sys
from collections import defaultdict
from sqlite3 import IntegrityError
from types import TracebackType
from typing import Self

from args import CLIArgs
from schemas import SchemaRemoteSigner
from schemas.keymanager_api import (
    DeleteStatus,
    DeleteStatusMessage,
    EthAddress,
    ImportStatus,
    ImportStatusMessage,
    Pubkey,
    RemoteKey,
    SignedVoluntaryExit,
    UInt64String,
    ValidatorFeeRecipient,
    ValidatorGasLimit,
    ValidatorGraffiti,
    VoluntaryExit,
)

from .beacon_chain import BeaconChain
from .db.db import DB
from .multi_beacon_node import MultiBeaconNode
from .remote_signer import RemoteSigner
from .signature_provider import SignatureProvider


class PubkeyNotFound(Exception):
    def __init__(self, pubkey: Pubkey):
        self.pubkey = pubkey


class Keymanager(SignatureProvider):
    def __init__(
        self,
        db: DB,
        beacon_chain: BeaconChain,
        multi_beacon_node: MultiBeaconNode,
        cli_args: CLIArgs,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.db = db
        self.beacon_chain = beacon_chain
        self.multi_beacon_node = multi_beacon_node

        self.enabled = cli_args.enable_keymanager_api
        self.pubkey_to_remote_signer: dict[str, RemoteSigner] = {}

        if self.enabled:
            # Spin up API app
            from api.keymanager import start_server

            # do not actually start a server while running tests
            if "pytest" in sys.modules:
                return
            self.api_task = asyncio.create_task(
                start_server(keymanager=self, cli_args=cli_args)
            )

    async def __aenter__(self) -> Self:
        await self._update_pubkey_to_remote_signer_mapping()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if hasattr(self, "api_task"):
            self.api_task.cancel()
        for signer in self.pubkey_to_remote_signer.values():
            await signer.__aexit__(exc_type, exc_val, exc_tb)

    async def _update_pubkey_to_remote_signer_mapping(self) -> None:
        for pubkey, url in self.db.fetch_all(
            "SELECT pubkey, url FROM keymanager_data;"
        ):
            existing_signer = self.pubkey_to_remote_signer.get(pubkey)
            if existing_signer and existing_signer.url == url:
                # Mapping already correct for this pubkey
                continue

            # Check if there's already an instantiated signer for the url
            try:
                signer = next(
                    s for _, s in self.pubkey_to_remote_signer.items() if s.url == url
                )
                self.pubkey_to_remote_signer[pubkey] = signer
            except StopIteration:
                # We need to instantiate a new RemoteSigner
                self.pubkey_to_remote_signer[pubkey] = await RemoteSigner(
                    url
                ).__aenter__()

    def get_fee_recipient(self, pubkey: Pubkey) -> ValidatorFeeRecipient:
        res, rowcount = self.db.fetch_one(
            "SELECT fee_recipient FROM keymanager_data WHERE pubkey=?;", (pubkey,)
        )
        if res is None:
            raise PubkeyNotFound(pubkey)

        return ValidatorFeeRecipient(pubkey=pubkey, ethaddress=res[0])

    def get_fee_recipient_override_values(
        self, pubkeys: list[Pubkey]
    ) -> dict[Pubkey, EthAddress]:
        return_dict = {
            pk: fr
            for pk, fr in self.db.fetch_all(
                f"SELECT pubkey, fee_recipient FROM keymanager_data WHERE pubkey IN ({','.join('?' for _ in pubkeys)});",  # noqa: S608
                (*pubkeys,),
            )
            if fr is not None
        }

        self.logger.debug(f"Retrieved overridden fee recipient values: {return_dict}")
        return return_dict

    def get_gas_limit_override_values(
        self, pubkeys: list[Pubkey]
    ) -> dict[Pubkey, UInt64String]:
        return_dict = {
            pk: gl
            for pk, gl in self.db.fetch_all(
                f"SELECT pubkey, gas_limit FROM keymanager_data WHERE pubkey IN ({','.join('?' for _ in pubkeys)});",  # noqa: S608
                (*pubkeys,),
            )
            if gl is not None
        }

        self.logger.debug(f"Retrieved overridden gas limit values: {return_dict}")
        return return_dict

    def set_fee_recipient(self, pubkey: Pubkey, fee_recipient: EthAddress) -> None:
        res, rowcount = self.db.fetch_one(
            "UPDATE keymanager_data SET fee_recipient=? WHERE pubkey=?;",
            (fee_recipient, pubkey),
        )
        if rowcount == 0:
            raise PubkeyNotFound(pubkey)

    def delete_configured_fee_recipient(self, pubkey: Pubkey) -> None:
        res, rowcount = self.db.fetch_one(
            "UPDATE keymanager_data SET fee_recipient=? WHERE pubkey=?;",
            (None, pubkey),
        )
        if rowcount == 0:
            raise PubkeyNotFound(pubkey)

    def get_gas_limit(self, pubkey: Pubkey) -> ValidatorGasLimit:
        res, rowcount = self.db.fetch_one(
            "SELECT gas_limit FROM keymanager_data WHERE pubkey=?;", (pubkey,)
        )
        if res is None:
            raise PubkeyNotFound(pubkey)

        return ValidatorGasLimit(pubkey=pubkey, gas_limit=res[0])

    def set_gas_limit(self, pubkey: Pubkey, gas_limit: UInt64String) -> None:
        res, rowcount = self.db.fetch_one(
            "UPDATE keymanager_data SET gas_limit=? WHERE pubkey=?;",
            (gas_limit, pubkey),
        )
        if rowcount == 0:
            raise PubkeyNotFound(pubkey)

    def delete_configured_gas_limit(self, pubkey: Pubkey) -> None:
        res, rowcount = self.db.fetch_one(
            "UPDATE keymanager_data SET gas_limit=? WHERE pubkey=?;",
            (None, pubkey),
        )
        if rowcount == 0:
            raise PubkeyNotFound(pubkey)

    def get_graffiti(self, pubkey: Pubkey) -> ValidatorGraffiti:
        res, rowcount = self.db.fetch_one(
            "SELECT graffiti FROM keymanager_data WHERE pubkey=?;", (pubkey,)
        )
        if res is None:
            raise PubkeyNotFound(pubkey)

        return ValidatorGraffiti(pubkey=pubkey, graffiti=res[0])

    def set_graffiti(self, pubkey: Pubkey, graffiti: str) -> None:
        res, rowcount = self.db.fetch_one(
            "UPDATE keymanager_data SET graffiti=? WHERE pubkey=?;",
            (graffiti, pubkey),
        )
        if rowcount == 0:
            raise PubkeyNotFound(pubkey)

    def delete_configured_graffiti_value(self, pubkey: Pubkey) -> None:
        res, rowcount = self.db.fetch_one(
            "UPDATE keymanager_data SET graffiti=? WHERE pubkey=?;",
            (None, pubkey),
        )
        if rowcount == 0:
            raise PubkeyNotFound(pubkey)

    def list_remote_keys(self) -> list[RemoteKey]:
        return [
            RemoteKey(pk, url)
            for pk, url in self.db.fetch_all("SELECT pubkey, url FROM keymanager_data;")
        ]

    async def import_remote_keys(
        self, remote_keys: list[RemoteKey]
    ) -> list[ImportStatusMessage]:
        import_status_messages: list[ImportStatusMessage] = []

        for remote_key in remote_keys:
            try:
                self.db.fetch_one(
                    "INSERT INTO keymanager_data VALUES (?, ?, ?, ?, ?);",
                    (remote_key.pubkey, remote_key.url, None, None, None),
                )
            except Exception as e:
                if (
                    isinstance(e, IntegrityError)
                    and repr(e)
                    == "IntegrityError('UNIQUE constraint failed: keymanager_data.pubkey')"
                ):
                    response_status = ImportStatus.DUPLICATE
                    message = ""
                else:
                    response_status = ImportStatus.ERROR
                    message = repr(e)
            else:
                response_status = ImportStatus.IMPORTED
                message = ""
            finally:
                import_status_messages.append(
                    ImportStatusMessage(
                        status=response_status,
                        message=message,
                    )
                )

        await self._update_pubkey_to_remote_signer_mapping()

        return import_status_messages

    async def delete_remote_keys(
        self, pubkeys: list[Pubkey]
    ) -> list[DeleteStatusMessage]:
        delete_status_messages: list[DeleteStatusMessage] = []

        for pubkey in pubkeys:
            try:
                res, rowcount = self.db.fetch_one(
                    "DELETE FROM keymanager_data WHERE pubkey=?;", (pubkey,)
                )
            except Exception as e:
                response_status = DeleteStatus.ERROR
                message = repr(e)
            else:
                if rowcount == 0:
                    response_status = DeleteStatus.NOT_FOUND
                else:
                    response_status = DeleteStatus.DELETED
                message = ""
            finally:
                delete_status_messages.append(
                    DeleteStatusMessage(
                        status=response_status,
                        message=message,
                    )
                )

        await self._update_pubkey_to_remote_signer_mapping()

        return delete_status_messages

    async def sign_voluntary_exit_message(
        self, pubkey: Pubkey, epoch: int | None
    ) -> SignedVoluntaryExit:
        # Get remote signer for pubkey
        res, rowcount = self.db.fetch_one(
            "SELECT url FROM keymanager_data WHERE pubkey=?;", (pubkey,)
        )
        if res is None:
            raise PubkeyNotFound(pubkey)

        # Determine if validator is active and its validator index
        if self.multi_beacon_node is None:
            raise ValueError("Keymanager.multi_beacon_node is None")

        val_idx_pubkeys = await self.multi_beacon_node.get_validators(
            ids=[pubkey],
        )
        if len(val_idx_pubkeys) == 0:
            raise ValueError(f"Failed to find validator index for pubkey: {pubkey}")

        validator_index = next(iter(val_idx_pubkeys)).index

        # Per Keymanager API spec - if no epoch is provided, use the current one
        epoch = epoch or self.beacon_chain.current_epoch

        msg, sig, pubkey = await self.sign(
            message=SchemaRemoteSigner.VoluntaryExitSignableMessage(
                fork_info=self.beacon_chain.get_fork_info(
                    slot=self.beacon_chain.spec.SLOTS_PER_EPOCH * epoch
                ),
                voluntary_exit=SchemaRemoteSigner.VoluntaryExit(
                    epoch=str(epoch), validator_index=str(validator_index)
                ),
            ),
            identifier=pubkey,
        )
        return SignedVoluntaryExit(
            message=VoluntaryExit(
                epoch=str(epoch),
                validator_index=str(validator_index),
            ),
            signature=sig,
        )

    async def sign(
        self,
        message: SchemaRemoteSigner.SignableMessageT,
        identifier: str,
    ) -> tuple[SchemaRemoteSigner.SignableMessageT, str, str]:
        signer = self.pubkey_to_remote_signer.get(identifier)

        if signer is None:
            # This can happen when a key is deleted but a duty had already been
            # scheduled for it. A signature for something will be requested,
            # Keymanager will raise in this case.
            raise PubkeyNotFound(identifier)

        return await signer.sign(
            message=message,
            identifier=identifier,
        )

    async def sign_in_batches(
        self,
        messages: list[SchemaRemoteSigner.SignableMessageT],
        identifiers: list[str],
        batch_size: int = 100,
    ) -> list[tuple[SchemaRemoteSigner.SignableMessageT, str, str]]:
        signer_inputs: defaultdict[
            RemoteSigner, tuple[list[SchemaRemoteSigner.SignableMessageT], list[str]]
        ] = defaultdict(lambda: ([], []))

        for message, identifier in zip(messages, identifiers, strict=False):
            signer = self.pubkey_to_remote_signer.get(identifier)
            if signer is None:
                # This can happen when a key is deleted but a duty had already been
                # scheduled for it. A signature for something will be requested,
                # Keymanager will log a warning here and NOT sign the message.
                self.logger.warning(
                    f"No signer found for {identifier} - not signing message"
                )
                continue

            signer_inputs[signer][0].append(message)
            signer_inputs[signer][1].append(identifier)

        tasks = [
            signer.sign_in_batches(messages, identifiers, batch_size)
            for signer, (messages, identifiers) in signer_inputs.items()
        ]
        results = await asyncio.gather(*tasks)

        # Flatten the list of results
        return [item for sublist in results for item in sublist]

    async def get_public_keys(self) -> list[Pubkey]:
        return [
            row for (row,) in self.db.fetch_all("SELECT pubkey FROM keymanager_data;")
        ]
