"""Provides methods for interacting with a remote signer through the [Remote Signing API](https://github.com/ethereum/remote-signing-api)."""

import asyncio
import functools
import logging
from concurrent.futures import ProcessPoolExecutor
from types import TracebackType
from typing import Self
from urllib.parse import urlparse

import aiohttp
import msgspec.json
from prometheus_client import Counter

from observability import get_service_name, get_service_version
from observability.api_client import RequestLatency, ServiceType
from schemas import SchemaRemoteSigner

_SIGNED_MESSAGES = Counter(
    "signed_messages",
    "Number of signed messages",
    labelnames=["signable_message_type"],
)


def _sign_messages_in_separate_process(
    remote_signer_url: str,
    messages: list[SchemaRemoteSigner.SignableMessageT],
    identifiers: list[str],
    batch_size: int,
) -> list[tuple[SchemaRemoteSigner.SignableMessageT, str, str]]:
    async def _sign_messages() -> list[
        tuple[SchemaRemoteSigner.SignableMessageT, str, str]
    ]:
        results = []
        async with RemoteSigner(url=remote_signer_url) as signer:
            for i in range(0, len(messages), batch_size):
                messages_batch = messages[i : i + batch_size]
                identifiers_batch = identifiers[i : i + batch_size]
                tasks = [
                    signer.sign(msg, identifier)
                    for msg, identifier in zip(
                        messages_batch,
                        identifiers_batch,
                        strict=True,
                    )
                ]
                results.extend(await asyncio.gather(*tasks))
        return results

    return asyncio.run(_sign_messages())


class RemoteSigner:
    def __init__(self, url: str):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.url = url
        self.host = urlparse(url).hostname or ""

        self.process_pool_executor = ProcessPoolExecutor()

    async def __aenter__(self) -> Self:
        if not self.host:
            raise ValueError(f"Failed to parse hostname from {self.url}")

        _user_agent = f"{get_service_name()}/{get_service_version()}"

        self._trace_default_request_ctx = dict(
            host=self.host or "",
            service_type=ServiceType.REMOTE_SIGNER.value,
        )

        # web3signer defaults to 20 vertx workers for handling signing requests
        # Using 2 aiohttp ClientSessions here - one for lower priority
        # signing requests like selection proofs, aggregations.
        # That session may use up to 10 connections at once.
        # Then there's the high priority session for things like
        # signing blocks and attestations, where
        # every ms counts.
        self.low_priority_client_session = aiohttp.ClientSession(
            base_url=self.url,
            connector=aiohttp.TCPConnector(limit=10),
            headers={"User-Agent": _user_agent},
            trace_configs=[
                RequestLatency(
                    host=self.host,
                    service_type=ServiceType.REMOTE_SIGNER,
                ),
            ],
            # Default aiohttp read buffer is only 64KB which is not always enough,
            # resulting in ValueError("Chunk too big")
            read_bufsize=2**19,
        )

        self.high_priority_client_session = aiohttp.ClientSession(
            base_url=self.url,
            headers={"User-Agent": _user_agent},
            trace_configs=[
                RequestLatency(
                    host=self.host,
                    service_type=ServiceType.REMOTE_SIGNER,
                ),
            ],
            # Default aiohttp read buffer is only 64KB which is not always enough,
            # resulting in ValueError("Chunk too big")
            read_bufsize=2**19,
        )

        self.json_encoder = msgspec.json.Encoder()

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        for session in (
            self.low_priority_client_session,
            self.high_priority_client_session,
        ):
            if not session.closed:
                await session.close()
        self.process_pool_executor.shutdown(wait=False, cancel_futures=True)

    async def get_public_keys(self) -> list[str]:
        _endpoint = "/api/v1/eth2/publicKeys"

        async with self.low_priority_client_session.get(_endpoint) as resp:
            if not resp.ok:
                raise ValueError(
                    f"NOK status code received ({resp.status}) from remote signer: {await resp.text()}",
                )

            pubkeys: list[str] = await resp.json()
            return pubkeys

    def _get_session_for_message(
        self,
        message: SchemaRemoteSigner.SignableMessage,
    ) -> aiohttp.ClientSession:
        high_priority_types = (
            SchemaRemoteSigner.BeaconBlockV2SignableMessage,
            SchemaRemoteSigner.RandaoRevealSignableMessage,
            SchemaRemoteSigner.AttestationSignableMessage,
            SchemaRemoteSigner.SyncCommitteeMessageSignableMessage,
        )
        return (
            self.high_priority_client_session
            if isinstance(message, high_priority_types)
            else self.low_priority_client_session
        )

    async def sign(
        self,
        message: SchemaRemoteSigner.SignableMessageT,
        identifier: str,
    ) -> tuple[SchemaRemoteSigner.SignableMessageT, str, str]:
        """:param message: SignableMessage to sign
        :param identifier: BLS public key in hex format for which data to sign
        :
        """
        _endpoint = "/api/v1/eth2/sign/{identifier}"

        async with self._get_session_for_message(message).post(
            _endpoint.format(identifier=identifier),
            data=self.json_encoder.encode(message),
            trace_request_ctx=dict(
                path=_endpoint,
                request_type=message.__class__.__name__,
            ),
        ) as resp:
            if not resp.ok:
                raise ValueError(
                    f"NOK status code received ({resp.status}) from remote signer: {await resp.text()}",
                )

            _SIGNED_MESSAGES.labels(signable_message_type=type(message).__name__).inc()
            return message, (await resp.json())["signature"], identifier

    async def sign_in_batches(
        self,
        messages: list[SchemaRemoteSigner.SignableMessageT],
        identifiers: list[str],
        batch_size: int = 100,
    ) -> list[tuple[SchemaRemoteSigner.SignableMessageT, str, str]]:
        """Signs messages in batches and returns a list of tuples containing the message,
        its signature, and the corresponding identifier.

        :param messages: List of SignableMessage objects to sign.
        :param identifiers: List of corresponding identifiers that should be used to
                            sign the messages.
        :param batch_size: Size of the batch of messages to sign in each iteration.
        :return: List of tuples (SignableMessage, signature, identifier).

        Large amounts of messages (more than `batch_size`) are signed in a separate
        process to avoid blocking the event loop.
        """
        if len(messages) != len(identifiers):
            raise ValueError(
                "Number of messages does not match the number of identifiers",
            )

        if len(messages) <= batch_size:
            return await asyncio.gather(
                *(
                    self.sign(message, identifier)
                    for message, identifier in zip(messages, identifiers, strict=False)
                ),
            )

        # For large amounts of messages, run the signing process in a separate
        # process to avoid blocking the event loop for too long
        loop = asyncio.get_running_loop()
        self.logger.debug(f"Signing {len(messages)} messages in a separate process")
        return await loop.run_in_executor(
            self.process_pool_executor,
            functools.partial(
                _sign_messages_in_separate_process,
                remote_signer_url=self.url,
                messages=messages,
                identifiers=identifiers,
                batch_size=batch_size,
            ),
        )
