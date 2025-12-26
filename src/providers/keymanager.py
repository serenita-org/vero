import asyncio
import contextlib
import logging
import sys
from collections import defaultdict
from sqlite3 import IntegrityError
from typing import TYPE_CHECKING, Self

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
from spec.utils import decode_graffiti

from .remote_signer import RemoteSigner
from .signature_provider import SignatureProvider

if TYPE_CHECKING:
    from types import TracebackType

    from .db.db import DB
    from .multi_beacon_node import MultiBeaconNode
    from .vero import Vero


class PubkeyNotFound(Exception):
    def __init__(self, pubkey: Pubkey):
        self.pubkey = pubkey


class Keymanager(SignatureProvider):
    def __init__(
        self,
        db: DB,
        multi_beacon_node: MultiBeaconNode,
        vero: Vero,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.db = db
        self.beacon_chain = vero.beacon_chain
        self.multi_beacon_node = multi_beacon_node
        self.cli_args = vero.cli_args
        self.vero = vero

        self.enabled = vero.cli_args.enable_keymanager_api
        self.pubkey_to_remote_signer: dict[str, RemoteSigner] = {}
        self.pubkey_to_fee_recipient_override: dict[str, EthAddress] = {}
        self.pubkey_to_gas_limit_override: dict[str, UInt64String] = {}
        self.pubkey_to_graffiti_override: dict[str, str] = {}

        # Create an AsyncExitStack for dynamically managed signers
        self._exit_stack = contextlib.AsyncExitStack()

        if self.enabled:
            self.pubkey_to_fee_recipient_override = self._load_fee_recipient_override()
            self.pubkey_to_gas_limit_override = self._load_gas_limit_override()
            self.pubkey_to_graffiti_override = self._load_graffiti_override()

            # Spin up API app
            from api.keymanager import start_server

            # do not actually start a server while running tests
            if "pytest" in sys.modules:
                return
            self.api_task = asyncio.create_task(
                start_server(keymanager=self, cli_args=vero.cli_args)
            )

    async def __aenter__(self) -> Self:
        await self._exit_stack.__aenter__()

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

        # Let the stack close all signers in reverse order
        await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)

    async def _update_pubkey_to_remote_signer_mapping(self) -> None:
        """
        Update the pubkey-to-RemoteSigner mapping based on records in keymanager_data.
        Any pubkey not in the DB is removed.

        - If a pubkey already has a matching RemoteSigner (same URL), it is reused.
        - If another pubkey's RemoteSigner (same URL) can be reused, do so.
        - Otherwise, a new RemoteSigner is instantiated.
        """
        # Fetch all (pubkey, url) pairs from the DB
        rows = self.db.fetch_all("SELECT pubkey, url FROM keymanager_data;")

        # Keep a quick-lookup dict from URL -> RemoteSigner so we can easily
        # reuse any existing signers without scanning pubkey_to_remote_signer.
        signers_by_url = {
            signer.url: signer for signer in self.pubkey_to_remote_signer.values()
        }

        # Build a new mapping for pubkey -> RemoteSigner
        new_mapping = {}

        for pubkey, url in rows:
            # If the pubkey already has a matching signer, just reuse it
            existing_signer = self.pubkey_to_remote_signer.get(pubkey)
            if existing_signer and existing_signer.url == url:
                new_mapping[pubkey] = existing_signer
                continue

            # Otherwise, see if we can reuse a signer from signers_by_url
            signer = signers_by_url.get(url)
            if signer is not None:
                new_mapping[pubkey] = signer
                continue

            # If we still don't have a signer, create a new one
            signer = await self._exit_stack.enter_async_context(
                RemoteSigner(
                    url,
                    vero=self.vero,
                )
            )
            signers_by_url[url] = signer
            new_mapping[pubkey] = signer

        # Overwrite the old mapping with the new one
        # This automatically drops any pubkey not present in the DB anymore
        self.pubkey_to_remote_signer = new_mapping

    def _load_fee_recipient_override(self) -> dict[str, str]:
        return {
            pk: fr
            for pk, fr in self.db.fetch_all(
                "SELECT pubkey, fee_recipient FROM keymanager_data;",
            )
            if fr is not None
        }

    def _load_gas_limit_override(self) -> dict[str, str]:
        return {
            pk: gl
            for pk, gl in self.db.fetch_all(
                "SELECT pubkey, gas_limit FROM keymanager_data;",
            )
            if gl is not None
        }

    def _load_graffiti_override(self) -> dict[str, str]:
        return {
            pk: graffiti
            for pk, graffiti in self.db.fetch_all(
                "SELECT pubkey, graffiti FROM keymanager_data;",
            )
            if graffiti is not None
        }

    def get_fee_recipient(self, pubkey: Pubkey) -> ValidatorFeeRecipient:
        res, _ = self.db.fetch_one(
            "SELECT fee_recipient FROM keymanager_data WHERE pubkey=?;", (pubkey,)
        )
        if res is None:
            raise PubkeyNotFound(pubkey)

        # If the fee recipient value was not overridden, return
        # the default fee recipient
        address = res[0] or self.cli_args.fee_recipient
        return ValidatorFeeRecipient(pubkey=pubkey, ethaddress=address)

    def set_fee_recipient(self, pubkey: Pubkey, fee_recipient: EthAddress) -> None:
        _, rowcount = self.db.fetch_one(
            "UPDATE keymanager_data SET fee_recipient=? WHERE pubkey=?;",
            (fee_recipient, pubkey),
        )
        if rowcount == 0:
            raise PubkeyNotFound(pubkey)
        self.pubkey_to_fee_recipient_override[pubkey] = fee_recipient

    def delete_configured_fee_recipient(self, pubkey: Pubkey) -> None:
        _, rowcount = self.db.fetch_one(
            "UPDATE keymanager_data SET fee_recipient=? WHERE pubkey=?;",
            (None, pubkey),
        )
        if rowcount == 0:
            raise PubkeyNotFound(pubkey)
        with contextlib.suppress(KeyError):
            del self.pubkey_to_fee_recipient_override[pubkey]

    def get_gas_limit(self, pubkey: Pubkey) -> ValidatorGasLimit:
        res, _ = self.db.fetch_one(
            "SELECT gas_limit FROM keymanager_data WHERE pubkey=?;", (pubkey,)
        )
        if res is None:
            raise PubkeyNotFound(pubkey)

        # If the gas limit value was not overridden, return
        # the default gas limit
        gas_limit = res[0] or str(self.cli_args.gas_limit)
        return ValidatorGasLimit(pubkey=pubkey, gas_limit=gas_limit)

    def set_gas_limit(self, pubkey: Pubkey, gas_limit: UInt64String) -> None:
        _, rowcount = self.db.fetch_one(
            "UPDATE keymanager_data SET gas_limit=? WHERE pubkey=?;",
            (gas_limit, pubkey),
        )
        if rowcount == 0:
            raise PubkeyNotFound(pubkey)
        self.pubkey_to_gas_limit_override[pubkey] = gas_limit

    def delete_configured_gas_limit(self, pubkey: Pubkey) -> None:
        _, rowcount = self.db.fetch_one(
            "UPDATE keymanager_data SET gas_limit=? WHERE pubkey=?;",
            (None, pubkey),
        )
        if rowcount == 0:
            raise PubkeyNotFound(pubkey)
        with contextlib.suppress(KeyError):
            del self.pubkey_to_gas_limit_override[pubkey]

    def get_graffiti(self, pubkey: Pubkey) -> ValidatorGraffiti:
        res, _ = self.db.fetch_one(
            "SELECT graffiti FROM keymanager_data WHERE pubkey=?;", (pubkey,)
        )
        if res is None:
            raise PubkeyNotFound(pubkey)

        graffiti = res[0] or decode_graffiti(self.cli_args.graffiti)
        return ValidatorGraffiti(pubkey=pubkey, graffiti=graffiti)

    def set_graffiti(self, pubkey: Pubkey, graffiti: str) -> None:
        _, rowcount = self.db.fetch_one(
            "UPDATE keymanager_data SET graffiti=? WHERE pubkey=?;",
            (graffiti, pubkey),
        )
        if rowcount == 0:
            raise PubkeyNotFound(pubkey)
        self.pubkey_to_graffiti_override[pubkey] = graffiti

    def delete_configured_graffiti_value(self, pubkey: Pubkey) -> None:
        _, rowcount = self.db.fetch_one(
            "UPDATE keymanager_data SET graffiti=? WHERE pubkey=?;",
            (None, pubkey),
        )
        if rowcount == 0:
            raise PubkeyNotFound(pubkey)
        with contextlib.suppress(KeyError):
            del self.pubkey_to_graffiti_override[pubkey]

    def list_remote_keys(self) -> list[RemoteKey]:
        return [
            RemoteKey(pk, signer.url)
            for pk, signer in self.pubkey_to_remote_signer.items()
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
                _, rowcount = self.db.fetch_one(
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
        # Determine if validator is active and its validator index
        val_idx_pubkeys = await self.multi_beacon_node.get_validators(
            ids=[pubkey],
        )
        if len(val_idx_pubkeys) == 0:
            raise ValueError(f"Failed to find validator index for pubkey: {pubkey}")

        validator_index = next(iter(val_idx_pubkeys)).index

        # Per Keymanager API spec - if no epoch is provided, use the current one
        if epoch is None:
            epoch = self.beacon_chain.current_epoch

        msg, sig, pubkey = await self.sign(
            message=SchemaRemoteSigner.VoluntaryExitSignableMessage(
                fork_info=self.beacon_chain.get_fork_info(
                    slot=self.beacon_chain.SLOTS_PER_EPOCH * epoch
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
