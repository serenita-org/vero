"""Provides methods for interacting with a beacon node through the [Beacon Node API](https://github.com/ethereum/beacon-APIs)."""

import asyncio
import datetime
import json
import logging
from collections.abc import AsyncIterable
from typing import Any
from urllib.parse import urlparse

import aiohttp
import msgspec
import pytz
from aiohttp import ClientTimeout
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from prometheus_client import Gauge, Histogram
from remerkleable.complex import Container
from yarl import URL

from observability import get_service_name, get_service_version
from observability.api_client import RequestLatency, ServiceType
from schemas import SchemaBeaconAPI, SchemaRemoteSigner, SchemaValidator
from spec.attestation import Attestation, AttestationData
from spec.base import Genesis, Spec, parse_spec
from spec.sync_committee import SyncCommitteeContributionClass

_TIMEOUT_DEFAULT_CONNECT = 1
_TIMEOUT_DEFAULT_TOTAL = 10
_SCORE_DELTA_SUCCESS = 1
_SCORE_DELTA_FAILURE = 5


_BEACON_NODE_SCORE = Gauge(
    "beacon_node_score",
    "Beacon node score",
    labelnames=["host"],
    multiprocess_mode="max",
)
_BEACON_NODE_VERSION = Gauge(
    "beacon_node_version",
    "Beacon node score",
    labelnames=["host", "version"],
    multiprocess_mode="max",
)
_block_value_buckets = [
    int(0.001 * 1e18),
    int(0.01 * 1e18),
    int(0.1 * 1e18),
    int(1 * 1e18),
    int(10 * 1e18),
]
_BEACON_NODE_CONSENSUS_BLOCK_VALUE = Histogram(
    "beacon_node_consensus_block_value",
    "Tracks the value of consensus layer rewards paid to the proposer in the block produced by this beacon node",
    labelnames=["host"],
    buckets=_block_value_buckets,
)
_BEACON_NODE_EXECUTION_PAYLOAD_VALUE = Histogram(
    "beacon_node_execution_payload_value",
    "Tracks the value of execution payloads in blocks produced by this beacon node",
    labelnames=["host"],
    buckets=_block_value_buckets,
)


class BeaconNodeNotReady(Exception):
    pass


class BeaconNodeUnsupportedEndpoint(Exception):
    pass


class BeaconNode:
    def __init__(self, base_url: str, scheduler: AsyncIOScheduler) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.getLogger().level)

        self.tracer = trace.get_tracer(self.__class__.__name__)

        self.base_url = URL(base_url)
        self.host = urlparse(base_url).hostname or ""
        if not self.host:
            raise ValueError(f"Failed to parse hostname from {base_url}")

        self.scheduler = scheduler

        self.initialized = False
        self._score = 0
        _BEACON_NODE_SCORE.labels(host=self.host).set(self._score)
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
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": f"{get_service_name()}/{get_service_version()}",
            },
            trace_configs=[
                RequestLatency(host=self.host, service_type=ServiceType.BEACON_NODE),
            ],
        )

        self.json_encoder = msgspec.json.Encoder()

    @property
    def score(self) -> int:
        return self._score

    @score.setter
    def score(self, value: int) -> None:
        self._score = max(0, min(value, 100))
        _BEACON_NODE_SCORE.labels(host=self.host).set(self._score)

    async def _initialize_full(self) -> None:
        self.genesis = await self.get_genesis()
        self.spec = await self.get_spec()
        self.node_version = await self.get_node_version()

        # Regularly refresh these values
        self.scheduler.add_job(self.get_spec, "interval", minutes=10)
        self.scheduler.add_job(self.get_node_version, "interval", minutes=10)

        self.score = 100
        self.initialized = True

    async def initialize_full(self, function: str | None = None) -> None:
        try:
            await self._initialize_full()
            self.logger.info(
                f"Initialized beacon node at {self.base_url}{f' [{function}]' if function else ''}",
            )
        except Exception as e:
            self.logger.error(
                f"Failed to initialize beacon node at {self.base_url}: {e!r}",
                exc_info=self.logger.isEnabledFor(logging.DEBUG),
            )
            # Retry initializing every 30 seconds
            next_run_time = datetime.datetime.now(tz=pytz.UTC) + datetime.timedelta(
                seconds=30,
            )
            self.scheduler.add_job(
                self.initialize_full,
                "date",
                next_run_time=next_run_time,
                kwargs=dict(function=function),
            )

    @staticmethod
    async def _handle_nok_status_code(response: aiohttp.ClientResponse) -> None:
        if response.ok:
            return

        resp_text = await response.text()

        if response.status == 503:
            raise BeaconNodeNotReady(resp_text)
        if response.status == 405:
            raise BeaconNodeUnsupportedEndpoint(resp_text)
        raise ValueError(
            f"Received status code {response.status} for request to {response.request_info.url}"
            f" Full response text: {resp_text}",
        )

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        formatted_endpoint_string_params: dict[str, str | int] | None = None,
        **kwargs: Any,
        # can't get this more correct type hint to work with mypy
        # **kwargs: Unpack[_RequestOptions],
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
                self.score += _SCORE_DELTA_SUCCESS
                return await resp.text()
        except BeaconNodeUnsupportedEndpoint:
            raise
        except Exception as e:
            self.logger.error(
                f"Failed to get response from {self.host} for {method} {endpoint}: {e!r}",
                exc_info=self.logger.isEnabledFor(logging.DEBUG),
            )
            self.score -= _SCORE_DELTA_FAILURE
            raise

    def _raise_if_optimistic(
        self,
        response: SchemaBeaconAPI.ExecutionOptimisticResponse,
    ) -> None:
        if response.execution_optimistic:
            raise ValueError(f"Execution optimistic on {self.host}")

    async def get_genesis(self) -> Genesis:
        resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/beacon/genesis",
        )
        return Genesis.from_obj(json.loads(resp)["data"])  # type: ignore[no-any-return]

    async def get_spec(self) -> Spec:
        resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/config/spec",
        )

        return parse_spec(json.loads(resp)["data"])

    async def get_node_version(self) -> str:
        resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/node/version",
        )

        try:
            version = json.loads(resp)["data"]["version"]
        except Exception as e:
            self.logger.warning(f"Failed to parse beacon node version: {e}")
            version = "unknown"

        if not isinstance(version, str):
            raise TypeError(
                f"Beacon node did not return a string version: {type(version)} : {version}",
            )

        _BEACON_NODE_VERSION.labels(host=self.host, version=version).set(1)
        return version

    async def produce_attestation_data(
        self,
        slot: int,
        committee_index: int,
    ) -> AttestationData:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.produce_attestation_data",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": self.host,
            },
        ) as tracer_span:
            resp = await self._make_request(
                method="GET",
                endpoint="/eth/v1/validator/attestation_data",
                params=dict(
                    slot=slot,
                    committee_index=committee_index,
                ),
                timeout=ClientTimeout(
                    connect=self.client_session.timeout.connect,
                    total=0.3,
                ),
            )

            att_data = AttestationData.from_obj(json.loads(resp)["data"])
            tracer_span.add_event(
                "AttestationData",
                attributes={
                    "att_data.beacon_block_root": att_data.beacon_block_root.to_obj(),
                },
            )
            return att_data  # type: ignore[no-any-return]

    async def wait_for_attestation_data(
        self,
        expected_head_block_root: str,
        slot: int,
        committee_index: int,
    ) -> AttestationData:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.wait_for_attestation_data",
            attributes={
                "server.address": self.host,
            },
        ):
            while True:
                _request_start_time = asyncio.get_running_loop().time()

                try:
                    att_data = await self.produce_attestation_data(
                        slot=slot,
                        committee_index=committee_index,
                    )
                    if att_data.beacon_block_root.to_obj() == expected_head_block_root:
                        return att_data
                except Exception as e:
                    self.logger.error(
                        f"Failed to produce attestation data: {e!r}",
                        exc_info=self.logger.isEnabledFor(logging.DEBUG),
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

    async def _get_validators_fallback(
        self,
        ids: list[str],
        statuses: list[SchemaBeaconAPI.ValidatorStatus],
        state_id: str = "head",
    ) -> list[SchemaValidator.ValidatorIndexPubkey]:
        if len(ids) == 0:
            return []

        _endpoint = "/eth/v1/beacon/states/{state_id}/validators"

        _batch_size = 64

        results = []
        for i in range(0, len(ids), _batch_size):
            ids_batch = ids[i : i + _batch_size]

            resp_text = await self._make_request(
                method="GET",
                endpoint=_endpoint,
                formatted_endpoint_string_params=dict(state_id=state_id),
                params={
                    "id": ids_batch,
                    "status": [s.value for s in statuses],
                },
            )

            resp_decoded = msgspec.json.decode(
                resp_text, type=SchemaBeaconAPI.GetStateValidatorsResponse
            )

            results += [
                SchemaValidator.ValidatorIndexPubkey(
                    index=int(v.index),
                    pubkey=v.validator.pubkey,
                    status=v.status,
                )
                for v in resp_decoded.data
            ]
        return results

    async def get_validators(
        self,
        ids: list[str],
        statuses: list[SchemaBeaconAPI.ValidatorStatus],
        state_id: str = "head",
    ) -> list[SchemaValidator.ValidatorIndexPubkey]:
        if len(ids) == 0:
            return []

        try:
            resp_text = await self._make_request(
                method="POST",
                endpoint="/eth/v1/beacon/states/{state_id}/validators",
                formatted_endpoint_string_params=dict(state_id=state_id),
                data=self.json_encoder.encode(
                    {
                        "ids": ids,
                        "statuses": [s.value for s in statuses],
                    }
                ),
            )
        except BeaconNodeUnsupportedEndpoint:
            # Grandine doesn't support the POST endpoint yet
            # -> fall back to GET endpoint
            return await self._get_validators_fallback(
                ids=ids,
                statuses=statuses,
                state_id=state_id,
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

    async def publish_attestations(self, attestations: list[dict]) -> None:  # type: ignore[type-arg]
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/beacon/pool/attestations",
            data=self.json_encoder.encode(attestations),
        )

    async def prepare_beacon_committee_subscriptions(self, data: list[dict]) -> None:  # type: ignore[type-arg]
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/beacon_committee_subscriptions",
            data=self.json_encoder.encode(data),
        )

    async def prepare_sync_committee_subscriptions(self, data: list[dict]) -> None:  # type: ignore[type-arg]
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/sync_committee_subscriptions",
            data=self.json_encoder.encode(data),
        )

    async def get_aggregate_attestation(
        self,
        attestation_data: AttestationData,
    ) -> Attestation:
        resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/validator/aggregate_attestation",
            params=dict(
                attestation_data_root=f"0x{attestation_data.hash_tree_root().hex()}",
                slot=attestation_data.slot,
            ),
            timeout=ClientTimeout(
                connect=self.client_session.timeout.connect,
                total=int(self.spec.SECONDS_PER_SLOT)
                / int(self.spec.INTERVALS_PER_SLOT),
            ),
        )

        return Attestation.from_obj(json.loads(resp)["data"])  # type: ignore[no-any-return]

    async def publish_aggregate_and_proofs(
        self,
        signed_aggregate_and_proofs: list[tuple[dict, str]],  # type: ignore[type-arg]
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/aggregate_and_proofs",
            data=self.json_encoder.encode(
                [
                    dict(message=msg, signature=sig)
                    for msg, sig in signed_aggregate_and_proofs
                ]
            ),
        )

    async def get_sync_committee_contribution(
        self,
        slot: int,
        subcommittee_index: int,
        beacon_block_root: str,
    ) -> Container:
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
                total=int(self.spec.SECONDS_PER_SLOT)
                / int(self.spec.INTERVALS_PER_SLOT),
            ),
        )

        return SyncCommitteeContributionClass.Contribution.from_obj(
            json.loads(resp)["data"],
        )

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

            block_value: int = consensus_block_value + execution_payload_value
            self.logger.info(f"{self.host} returned block with value {block_value}")
            _BEACON_NODE_CONSENSUS_BLOCK_VALUE.labels(host=self.host).observe(
                consensus_block_value
            )
            _BEACON_NODE_EXECUTION_PAYLOAD_VALUE.labels(host=self.host).observe(
                execution_payload_value
            )

            return response

    async def publish_block_v2(
        self,
        block_version: SchemaBeaconAPI.BeaconBlockVersion,
        block: Container,
        blobs: list,  # type: ignore[type-arg]
        kzg_proofs: list,  # type: ignore[type-arg]
        signature: str,
    ) -> None:
        if block_version == SchemaBeaconAPI.BeaconBlockVersion.DENEB:
            data = dict(
                signed_block=dict(
                    message=block.to_obj(),
                    signature=signature,
                ),
                kzg_proofs=kzg_proofs,
                blobs=blobs,
            )
        else:
            raise NotImplementedError(f"Unsupported block version {block_version}")

        self.logger.debug(
            f"Publishing block for slot {block.slot},"
            f" block root {block.hash_tree_root().hex()},"
            f" body root {block.body.hash_tree_root().hex()}",
        )

        await self._make_request(
            method="POST",
            endpoint="/eth/v2/beacon/blocks",
            data=self.json_encoder.encode(data),
            headers={"Eth-Consensus-Version": block_version.value},
        )

    async def publish_blinded_block_v2(
        self,
        block_version: SchemaBeaconAPI.BeaconBlockVersion,
        block: Container,
        signature: str,
    ) -> None:
        if block_version == SchemaBeaconAPI.BeaconBlockVersion.DENEB:
            data = dict(
                message=block.to_obj(),
                signature=signature,
            )
        else:
            raise NotImplementedError(f"Unsupported block version {block_version}")

        self.logger.debug(
            f"Publishing blinded block for slot {block.slot},"
            f" block root {block.hash_tree_root().hex()},"
            f" body root {block.body.hash_tree_root().hex()}",
        )

        await self._make_request(
            method="POST",
            endpoint="/eth/v2/beacon/blinded_blocks",
            data=self.json_encoder.encode(data),
            headers={"Eth-Consensus-Version": block_version.value},
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
                decoded = (await anext(events_iter)).decode()
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
                    self.logger.error(
                        f"Failed to parse event name from {decoded} ({e!r}) -> ignoring event...",
                        exc_info=self.logger.isEnabledFor(logging.DEBUG),
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
                yield msgspec.json.decode(
                    event_data[0].split("data:")[1], type=event_struct
                )
