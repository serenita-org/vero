"""Provides methods for interacting with a beacon node through the [Beacon Node API](https://github.com/ethereum/beacon-APIs)."""

import asyncio
import contextlib
import datetime
import json
import logging
import warnings
from collections.abc import AsyncIterable
from typing import TYPE_CHECKING, Literal, Unpack
from urllib.parse import urlparse

import aiohttp
import msgspec
from aiohttp import ClientTimeout
from aiohttp.client import _RequestOptions
from aiohttp.hdrs import ACCEPT, CONTENT_TYPE, USER_AGENT
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from yarl import URL

from observability import (
    ErrorType,
    get_service_name,
    get_service_version,
)
from observability.api_client import RequestLatency, ServiceType
from providers._headers import ContentType
from schemas import SchemaBeaconAPI, SchemaRemoteSigner, SchemaValidator
from spec import SpecAttestation, SpecSyncCommittee
from spec.base import SpecFulu, parse_spec
from spec.constants import INTERVALS_PER_SLOT

if TYPE_CHECKING:
    from .vero import Vero

_TIMEOUT_DEFAULT_CONNECT = 1
_TIMEOUT_DEFAULT_TOTAL = 10


class BeaconNodeNotReady(Exception):
    pass


class BeaconNodeUnsupportedEndpoint(Exception):
    pass


class BeaconNodeReturnedBadRequest(Exception):
    pass


class BeaconNode:
    MAX_SCORE = 100
    SCORE_DELTA_SUCCESS = 1
    SCORE_DELTA_FAILURE = 5

    def __init__(
        self,
        base_url: str,
        vero: "Vero",
    ) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.metrics = vero.metrics
        self.tracer = trace.get_tracer(self.__class__.__name__)

        self.base_url = URL(base_url)
        self.host = urlparse(base_url).hostname or ""
        if not self.host:
            raise ValueError(f"Failed to parse hostname from {base_url}")

        self.spec = vero.spec
        self.SECONDS_PER_INTERVAL = int(self.spec.SECONDS_PER_SLOT) / INTERVALS_PER_SLOT

        self.scheduler = vero.scheduler
        self.task_manager = vero.task_manager

        self.initialized = False
        self._init_retry_interval = 5.0
        self._score = 0
        self.metrics.beacon_node_score_g.labels(host=self.host).set(0)
        self.metrics.checkpoint_confirmations_c.labels(host=self.host).reset()
        self.node_version = ""

        self._trace_default_request_ctx = dict(
            host=self.host,
            service_type=ServiceType.BEACON_NODE.value,
        )

        self.client_session = aiohttp.ClientSession(
            timeout=ClientTimeout(
                connect=_TIMEOUT_DEFAULT_CONNECT,
                total=_TIMEOUT_DEFAULT_TOTAL,
            ),
            headers={
                ACCEPT: ContentType.JSON.value,
                CONTENT_TYPE: ContentType.JSON.value,
                USER_AGENT: f"{get_service_name()}/{get_service_version()}",
            },
            trace_configs=[
                RequestLatency(host=self.host, service_type=ServiceType.BEACON_NODE),
            ],
            # Default aiohttp read buffer is only 64KB which is not always enough,
            # resulting in ValueError("Chunk too big")
            read_bufsize=2**19,
        )

        self.json_encoder = msgspec.json.Encoder()

    @property
    def score(self) -> int:
        return self._score

    @score.setter
    def score(self, value: int) -> None:
        self._score = max(0, min(value, BeaconNode.MAX_SCORE))
        self.metrics.beacon_node_score_g.labels(host=self.host).set(self._score)

    async def _initialize_full(self) -> None:
        # Raise if the spec returned by the beacon node differs
        bn_spec = await self.get_spec()
        if self.spec != bn_spec:
            msg = f"Spec values returned by beacon node {self.host} not equal to hardcoded spec values:"
            for field in self.spec.fields():
                if getattr(self.spec, field) != getattr(bn_spec, field):
                    msg += (
                        f"\n{field}:"
                        f"\n\tIncluded value: {getattr(self.spec, field)}"
                        f"\n\tValue returned by beacon node: {getattr(bn_spec, field)}"
                    )
            raise ValueError(msg)

        # Regularly refresh the version of the beacon node
        self.scheduler.add_job(
            self.update_node_version,
            "interval",
            minutes=10,
            next_run_time=datetime.datetime.now(tz=datetime.UTC),
            id=f"{self.__class__.__name__}.update_node_version-{self.base_url}",
        )

        self.score = BeaconNode.MAX_SCORE
        self.initialized = True

    async def initialize_full(self) -> None:
        try:
            await self._initialize_full()
            self.logger.info(
                f"Initialized beacon node at {self.base_url}",
            )
        except Exception as e:
            self.logger.exception(
                f"Failed to initialize beacon node at {self.base_url}: {e!r}. Retrying in {self._init_retry_interval} seconds.",
            )
            self.task_manager.create_task(
                self.initialize_full(), delay=self._init_retry_interval
            )

    @staticmethod
    async def _handle_nok_status_code(response: aiohttp.ClientResponse) -> None:
        if response.ok:
            return

        resp_text = await response.text()

        if response.status == 503:
            raise BeaconNodeNotReady(response.request_info.url, resp_text)
        if response.status == 405:
            raise BeaconNodeUnsupportedEndpoint(response.request_info.url, resp_text)
        if response.status == 400:
            raise BeaconNodeReturnedBadRequest(response.request_info.url, resp_text)

        raise ValueError(
            f"Received status code {response.status} for request to {response.request_info.url}"
            f" Full response text: {resp_text}",
        )

    async def _make_request(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        formatted_endpoint_string_params: dict[str, str | int] | None = None,
        **kwargs: Unpack[_RequestOptions],
    ) -> str:
        if formatted_endpoint_string_params is not None:
            kwargs["trace_request_ctx"] = dict(path=endpoint)
            endpoint = endpoint.format(**formatted_endpoint_string_params)

        # Intentionally setting full URL here
        # for testing reasons - we need
        # the full URL available there
        url = self.base_url.join(URL(endpoint))

        self.logger.debug(f"Making {method} request to {url}")
        try:
            async with self.client_session.request(
                method=method,
                url=url,
                **kwargs,
            ) as resp:
                await self._handle_nok_status_code(response=resp)

                # Request was successfully fulfilled
                self.score += BeaconNode.SCORE_DELTA_SUCCESS

                # The naive `resp.content_type` approach defaults to
                # a content type of `application/octet-stream` if
                # no Content-Type header is present in the response.
                # Therefore we can only check its value it
                # it is defined in the response header
                if (
                    resp.headers.get(CONTENT_TYPE) is not None
                    and resp.content_type != ContentType.JSON.value
                ):
                    raise NotImplementedError(  # noqa: TRY301
                        f"Content type in response unsupported: {resp.content_type}"
                    )

                return await resp.text()
        except BeaconNodeNotReady:
            self.score -= BeaconNode.SCORE_DELTA_FAILURE
            raise
        except Exception as e:
            self.logger.debug(
                f"Failed to get response from {self.host} for {method} {endpoint}: {e!r}",
            )
            self.score -= BeaconNode.SCORE_DELTA_FAILURE
            raise

    def _raise_if_optimistic(
        self,
        response: SchemaBeaconAPI.ExecutionOptimisticResponse,
    ) -> None:
        if response.execution_optimistic:
            raise ValueError(f"Execution optimistic on {self.host}")

    async def get_spec(self) -> SpecFulu:
        resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/config/spec",
        )

        return parse_spec(json.loads(resp)["data"])

    async def update_node_version(self) -> None:
        resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/node/version",
        )

        try:
            resp_version = json.loads(resp)["data"]["version"]
        except Exception as e:
            self.logger.warning(f"Failed to parse beacon node version: {e}")
            resp_version = "unknown"

        if not isinstance(resp_version, str):
            raise TypeError(
                f"Beacon node did not return a string version: {type(resp_version)} : {resp_version}",
            )

        if resp_version != self.node_version:
            self.logger.info(
                f"Beacon node version changed on {self.host}: {self.node_version} -> {resp_version}"
            )
            # Remove old metric value in order not to report multiple values
            # for the same host
            with contextlib.suppress(KeyError), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.metrics.beacon_node_version_g.remove(self.host, self.node_version)

        self.node_version = resp_version
        self.metrics.beacon_node_version_g.labels(
            host=self.host, version=self.node_version
        ).set(1)

    async def produce_attestation_data(
        self,
        slot: int,
    ) -> tuple[str, SchemaBeaconAPI.AttestationData]:
        """Returns the beacon node host along with the produced attestation data."""
        resp_text = await self._make_request(
            method="GET",
            endpoint="/eth/v1/validator/attestation_data",
            params=dict(
                slot=slot,
                committee_index=0,
            ),
            timeout=ClientTimeout(
                connect=self.client_session.timeout.connect,
                total=0.5,
            ),
        )

        response = msgspec.json.decode(
            resp_text, type=SchemaBeaconAPI.ProduceAttestationDataResponse
        )
        return self.host, response.data

    async def wait_for_attestation_data(
        self,
        expected_head_block_root: str,
        slot: int,
    ) -> SchemaBeaconAPI.AttestationData:
        while True:
            _request_start_time = asyncio.get_running_loop().time()

            try:
                _, att_data = await self.produce_attestation_data(
                    slot=slot,
                )
                if att_data.beacon_block_root == expected_head_block_root:
                    self.logger.debug(f"Got matching AttestationData from {self.host}")
                    return att_data
            except Exception as e:
                self.logger.debug(
                    f"Failed to produce attestation data: {e!r}",
                )

            # Rate-limiting - wait at least 50ms in between requests
            elapsed_time = asyncio.get_running_loop().time() - _request_start_time
            await asyncio.sleep(max(0.05 - elapsed_time, 0))

    async def wait_for_checkpoints(
        self,
        slot: int,
        expected_source_cp: SchemaBeaconAPI.Checkpoint,
        expected_target_cp: SchemaBeaconAPI.Checkpoint,
    ) -> None:
        while True:
            _request_start_time = asyncio.get_running_loop().time()

            try:
                _, att_data = await self.produce_attestation_data(
                    slot=slot,
                )
                if (
                    att_data.source == expected_source_cp
                    and att_data.target == expected_target_cp
                ):
                    self.logger.info(f"Finality checkpoints confirmed by {self.host}")
                    self.metrics.checkpoint_confirmations_c.labels(host=self.host).inc()
                    return
            except Exception as e:
                self.logger.warning(
                    f"Failed to produce attestation data while waiting for checkpoints: {e!r}",
                )

            # Rate-limiting - wait at least 50ms in between requests
            elapsed_time = asyncio.get_running_loop().time() - _request_start_time
            await asyncio.sleep(max(0.05 - elapsed_time, 0))

    async def get_block_root(self, block_id: str) -> str:
        resp_text = await self._make_request(
            method="GET",
            endpoint="/eth/v1/beacon/blocks/{block_id}/root",
            formatted_endpoint_string_params=dict(block_id=block_id),
            timeout=ClientTimeout(
                connect=self.client_session.timeout.connect,
                total=1,
            ),
        )

        response = msgspec.json.decode(
            resp_text, type=SchemaBeaconAPI.GetBlockRootResponse
        )
        self._raise_if_optimistic(response)

        return response.data.root

    async def get_validators(
        self,
        ids: list[str],
        statuses: list[SchemaBeaconAPI.ValidatorStatus] | None = None,
        state_id: str = "head",
    ) -> list[SchemaValidator.ValidatorIndexPubkey]:
        if len(ids) == 0:
            return []

        resp_text = await self._make_request(
            method="POST",
            endpoint="/eth/v1/beacon/states/{state_id}/validators",
            formatted_endpoint_string_params=dict(state_id=state_id),
            data=self.json_encoder.encode(
                {
                    "ids": ids,
                    "statuses": [s.value for s in statuses] if statuses else None,
                }
            ),
        )

        resp_decoded = msgspec.json.decode(
            resp_text, type=SchemaBeaconAPI.GetStateValidatorsResponse
        )

        return [
            SchemaValidator.ValidatorIndexPubkey(
                index=int(v.index),
                pubkey=v.validator.pubkey,
                status=v.status,
            )
            for v in resp_decoded.data
        ]

    async def get_attester_duties(
        self,
        epoch: int,
        indices: list[int],
    ) -> SchemaBeaconAPI.GetAttesterDutiesResponse:
        resp_text = await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/duties/attester/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
            data=self.json_encoder.encode([str(i) for i in indices]),
        )

        response = msgspec.json.decode(
            resp_text, type=SchemaBeaconAPI.GetAttesterDutiesResponse
        )
        self._raise_if_optimistic(response)

        return response

    async def get_proposer_duties(
        self,
        epoch: int,
    ) -> SchemaBeaconAPI.GetProposerDutiesResponse:
        resp_text = await self._make_request(
            method="GET",
            endpoint="/eth/v1/validator/duties/proposer/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
        )

        response = msgspec.json.decode(
            resp_text, type=SchemaBeaconAPI.GetProposerDutiesResponse
        )
        self._raise_if_optimistic(response)

        return response

    async def get_sync_duties(
        self,
        epoch: int,
        indices: list[int],
    ) -> SchemaBeaconAPI.GetSyncDutiesResponse:
        resp_text = await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/duties/sync/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
            data=self.json_encoder.encode([str(i) for i in indices]),
        )
        response = msgspec.json.decode(
            resp_text, type=SchemaBeaconAPI.GetSyncDutiesResponse
        )
        self._raise_if_optimistic(response)

        return response

    async def publish_sync_committee_messages(
        self,
        messages: list[dict[str, str]],
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/beacon/pool/sync_committees",
            data=self.json_encoder.encode(messages),
        )

    async def publish_attestations(
        self,
        attestations: list[SchemaBeaconAPI.SingleAttestation],
        fork_version: SchemaBeaconAPI.ForkVersion,
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v2/beacon/pool/attestations",
            data=self.json_encoder.encode(attestations),
            headers={"Eth-Consensus-Version": fork_version.value},
        )

    async def prepare_beacon_committee_subscriptions(
        self, data: list[SchemaBeaconAPI.SubscribeToBeaconCommitteeSubnetRequestBody]
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/beacon_committee_subscriptions",
            data=self.json_encoder.encode(data),
        )

    async def prepare_sync_committee_subscriptions(
        self, data: list[SchemaBeaconAPI.SubscribeToSyncCommitteeSubnetRequestBody]
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/sync_committee_subscriptions",
            data=self.json_encoder.encode(data),
        )

    async def get_aggregate_attestation_v2(
        self,
        attestation_data_root: str,
        slot: int,
        committee_index: int,
    ) -> "SpecAttestation.AttestationElectra":
        resp_text = await self._make_request(
            method="GET",
            endpoint="/eth/v2/validator/aggregate_attestation",
            params=dict(
                attestation_data_root=attestation_data_root,
                slot=slot,
                committee_index=committee_index,
            ),
            timeout=ClientTimeout(
                connect=self.client_session.timeout.connect,
                total=self.SECONDS_PER_INTERVAL,
            ),
        )

        response = msgspec.json.decode(
            resp_text, type=SchemaBeaconAPI.GetAggregatedAttestationV2Response
        )

        att = SpecAttestation.AttestationElectra.from_obj(response.data)

        self.metrics.beacon_node_aggregate_attestation_participant_count_h.labels(
            host=self.host
        ).observe(sum(att.aggregation_bits))
        return att

    async def publish_aggregate_and_proofs(
        self,
        signed_aggregate_and_proofs: list[tuple[dict, str]],  # type: ignore[type-arg]
        fork_version: SchemaBeaconAPI.ForkVersion,
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v2/validator/aggregate_and_proofs",
            data=self.json_encoder.encode(
                [
                    dict(message=msg, signature=sig)
                    for msg, sig in signed_aggregate_and_proofs
                ]
            ),
            headers={"Eth-Consensus-Version": fork_version.value},
        )

    async def get_sync_committee_contribution(
        self,
        slot: int,
        subcommittee_index: int,
        beacon_block_root: str,
    ) -> "SpecSyncCommittee.Contribution":
        resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/validator/sync_committee_contribution",
            params=dict(
                slot=slot,
                subcommittee_index=subcommittee_index,
                beacon_block_root=beacon_block_root,
            ),
            timeout=ClientTimeout(
                connect=self.client_session.timeout.connect,
                total=self.SECONDS_PER_INTERVAL,
            ),
        )

        contribution = SpecSyncCommittee.Contribution.from_obj(
            json.loads(resp)["data"],
        )
        self.metrics.beacon_node_sync_contribution_participant_count_h.labels(
            host=self.host
        ).observe(sum(contribution.aggregation_bits))
        return contribution

    async def publish_sync_committee_contribution_and_proofs(
        self,
        signed_contribution_and_proofs: list[tuple[dict, str]],  # type: ignore[type-arg]
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/contribution_and_proofs",
            data=self.json_encoder.encode(
                [
                    dict(message=contribution, signature=sig)
                    for contribution, sig in signed_contribution_and_proofs
                ]
            ),
        )

    async def prepare_beacon_proposer(self, data: list[dict[str, str]]) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/prepare_beacon_proposer",
            data=self.json_encoder.encode(data),
        )

    async def register_validator(
        self,
        signed_registrations: list[
            tuple[SchemaRemoteSigner.ValidatorRegistration, str]
        ],
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/register_validator",
            data=self.json_encoder.encode(
                [
                    dict(message=registration, signature=sig)
                    for registration, sig in signed_registrations
                ]
            ),
        )

    async def produce_block_v3(
        self,
        slot: int,
        graffiti: bytes,
        builder_boost_factor: int,
        randao_reveal: str,
    ) -> SchemaBeaconAPI.ProduceBlockV3Response:
        """Requests a beacon node to produce a valid block, which can then be signed by a validator.
        The returned block may be blinded or unblinded, depending on the current state of the network
        as decided by the execution and beacon nodes.

        The beacon node must return an unblinded block if it obtains the execution payload from
        its paired execution node. It must only return a blinded block if it obtains the execution
        payload header from an MEV relay.

        Metadata in the response indicates the type of block produced, and the supported types
        of blocks will be extended to as forks progress.
        """
        params = dict(
            randao_reveal=randao_reveal,
            builder_boost_factor=str(builder_boost_factor),
        )
        if graffiti:
            params["graffiti"] = f"0x{graffiti.hex()}"

        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.produce_block_v3",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": self.host,
            },
        ) as tracer_span:
            resp = await self._make_request(
                method="GET",
                endpoint="/eth/v3/validator/blocks/{slot}",
                formatted_endpoint_string_params=dict(slot=slot),
                params=params,
                timeout=ClientTimeout(
                    connect=self.client_session.timeout.connect,
                ),
            )

            response = msgspec.json.decode(
                resp, type=SchemaBeaconAPI.ProduceBlockV3Response
            )

            # Prysm may return an empty string for the block value
            # https://github.com/OffchainLabs/prysm/issues/15174
            response.consensus_block_value = response.consensus_block_value or "0"
            response.execution_payload_value = response.execution_payload_value or "0"

            consensus_block_value = int(response.consensus_block_value)
            execution_payload_value = int(response.execution_payload_value)

            tracer_span.add_event(
                "ProduceBlockV3Response",
                attributes=dict(
                    blinded=response.execution_payload_blinded,
                    execution_payload_value=execution_payload_value,
                    consensus_block_value=consensus_block_value,
                ),
            )

            self.logger.info(
                f"{self.host} returned block with"
                f" consensus block value {consensus_block_value},"
                f" execution payload value {execution_payload_value}."
            )
            self.metrics.beacon_node_consensus_block_value_h.labels(
                host=self.host
            ).observe(consensus_block_value)
            self.metrics.beacon_node_execution_payload_value_h.labels(
                host=self.host
            ).observe(execution_payload_value)

            return response

    async def publish_block_v2(
        self,
        fork_version: SchemaBeaconAPI.ForkVersion,
        signed_beacon_block_contents: SchemaBeaconAPI.BlockContentsSigned,
    ) -> None:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.publish_block_v2",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": self.host,
            },
        ):
            await self._make_request(
                method="POST",
                endpoint="/eth/v2/beacon/blocks",
                data=self.json_encoder.encode(signed_beacon_block_contents),
                headers={
                    "Eth-Consensus-Version": fork_version.value,
                    CONTENT_TYPE: ContentType.JSON.value,
                },
            )

    async def publish_blinded_block_v2(
        self,
        fork_version: SchemaBeaconAPI.ForkVersion,
        signed_blinded_beacon_block: SchemaBeaconAPI.SignedBeaconBlock,
    ) -> None:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.publish_blinded_block_v2",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": self.host,
            },
        ):
            await self._make_request(
                method="POST",
                endpoint="/eth/v2/beacon/blinded_blocks",
                data=self.json_encoder.encode(signed_blinded_beacon_block),
                headers={
                    "Eth-Consensus-Version": fork_version.value,
                    CONTENT_TYPE: ContentType.JSON.value,
                },
            )

    async def get_liveness(
        self, epoch: int, validator_indices: list[int]
    ) -> SchemaBeaconAPI.PostLivenessResponseBody:
        resp = await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/liveness/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
            timeout=ClientTimeout(
                connect=self.client_session.timeout.connect,
            ),
            data=self.json_encoder.encode([str(i) for i in validator_indices]),
        )

        return msgspec.json.decode(
            resp,
            type=SchemaBeaconAPI.PostLivenessResponseBody,
        )

    async def subscribe_to_events(
        self,
        topics: list[str],
    ) -> AsyncIterable[SchemaBeaconAPI.BeaconNodeEvent]:
        _event_name_to_struct_mapping: dict[
            str, type[SchemaBeaconAPI.BeaconNodeEvent]
        ] = dict(
            head=SchemaBeaconAPI.HeadEvent,
            chain_reorg=SchemaBeaconAPI.ChainReorgEvent,
            attester_slashing=SchemaBeaconAPI.AttesterSlashingEvent,
            proposer_slashing=SchemaBeaconAPI.ProposerSlashingEvent,
        )

        async with self.client_session.get(
            url=self.base_url.join(URL("/eth/v1/events")),
            params={"topics": topics},
            headers={"accept": "text/event-stream"},
            timeout=ClientTimeout(
                sock_connect=1, sock_read=None
            ),  # Defaults to 5 minutes
        ) as resp:
            # Minimal SSE client implementation
            events_iter = aiter(resp.content)
            while True:
                try:
                    decoded = (await anext(events_iter)).decode()
                except StopAsyncIteration:
                    break
                if decoded.startswith(":"):
                    self.logger.debug(f"SSE Comment {decoded}")
                    continue

                if not decoded.startswith("event:"):
                    if len(decoded.strip()) == 0:
                        # Just a keep-alive message
                        continue
                    self.logger.warning(
                        f"Unexpected message in beacon node event stream: {decoded!r}",
                    )
                    continue

                try:
                    event_name = decoded.split(":")[1].strip()
                except Exception as e:
                    self.metrics.errors_c.labels(
                        error_type=ErrorType.EVENT_CONSUMER.value,
                    ).inc()
                    self.logger.exception(
                        f"Failed to parse event name from {decoded} ({e!r}) -> ignoring event...",
                    )
                    continue

                event_data = []
                next_line = (await anext(events_iter)).decode()
                while next_line not in ("\n", "\r\n"):
                    event_data.append(next_line)
                    next_line = (await anext(events_iter)).decode()

                try:
                    event_struct = _event_name_to_struct_mapping[event_name]
                except KeyError:
                    raise NotImplementedError(
                        f"Unable to process event with name {event_name}, event_data: {event_data}!",
                    ) from None

                event = msgspec.json.decode(
                    event_data[0].split("data:")[1], type=event_struct
                )

                if (
                    hasattr(event, "execution_optimistic")
                    and event.execution_optimistic
                ):
                    raise ValueError(f"Execution optimistic for event: {event}")

                yield event
