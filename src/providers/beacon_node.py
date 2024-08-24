"""
Provides methods for interacting with a beacon node through the [Beacon Node API](https://github.com/ethereum/beacon-APIs).
"""

import asyncio
import datetime
import json
import logging
from urllib.parse import urlparse
from types import SimpleNamespace
from typing import AsyncIterable

import aiohttp
import pytz
from aiohttp import ClientTimeout
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from remerkleable.complex import Container
from prometheus_client import Gauge
from yarl import URL

from observability import get_service_name, get_service_version
from spec.attestation import Attestation, AttestationData
from observability.api_client import RequestLatency, ServiceType
from schemas import SchemaBeaconAPI, SchemaRemoteSigner, SchemaValidator
from spec.base import Spec, parse_spec, Genesis
from spec.sync_committee import SyncCommitteeContributionClass

_TIMEOUT_DEFAULT_CONNECT = 1
_TIMEOUT_DEFAULT_TOTAL = 10
_SCORE_DELTA_SUCCESS = 1
_SCORE_DELTA_FAILURE = 5


_BEACON_NODE_SCORE = Gauge(
    "beacon_node_score", "Beacon node score", labelnames=["host"]
)
_BEACON_NODE_VERSION = Gauge(
    "beacon_node_version", "Beacon node score", labelnames=["host", "version"]
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

        self.client_session = aiohttp.ClientSession(
            timeout=ClientTimeout(
                connect=_TIMEOUT_DEFAULT_CONNECT, total=_TIMEOUT_DEFAULT_TOTAL
            ),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": f"{get_service_name()}/{get_service_version()}",
            },
            trace_configs=[
                RequestLatency(
                    host=self.host,
                    service_type=ServiceType.BEACON_NODE,
                )
            ],
        )

    @property
    def score(self):
        return self._score

    @score.setter
    def score(self, value):
        self._score = max(0, min(value, 100))
        _BEACON_NODE_SCORE.labels(host=self.host).set(self._score)

    async def _initialize_full(self):
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
                f"Initialized beacon node at {self.base_url}{f' [{function}]' if function else ''}"
            )
        except Exception:
            self.logger.exception(
                f"Failed to initialize beacon node at {self.base_url}"
            )
            # Retry initializing every 30 seconds
            next_run_time = datetime.datetime.now(tz=pytz.UTC) + datetime.timedelta(
                seconds=30
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

        if response.status == 503:
            raise BeaconNodeNotReady(await response.text())
        elif response.status == 405:
            raise BeaconNodeUnsupportedEndpoint(await response.text())
        else:
            raise ValueError(
                f"Unexpected status code received: {response.status} for request to {response.request_info.url}"
                f"\nResponse text: {await response.text()}"
            )

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        formatted_endpoint_string_params: dict | None = None,
        **kwargs,
    ) -> str:
        if formatted_endpoint_string_params is not None:
            kwargs["trace_request_ctx"] = SimpleNamespace(path=endpoint)
            endpoint = endpoint.format(**formatted_endpoint_string_params)

        # Intentionally setting full URL here
        # for testing reasons - we need
        # the full URL available there
        url = self.base_url.join(URL(endpoint))

        self.logger.debug(f"Making {method} request to {url}")
        try:
            async with self.client_session.request(
                method=method, url=url, **kwargs
            ) as resp:
                await self._handle_nok_status_code(response=resp)

                # Request was successfully fulfilled
                self.score += _SCORE_DELTA_SUCCESS
                return await resp.text()
        except BeaconNodeUnsupportedEndpoint:
            raise
        except Exception:
            self.score -= _SCORE_DELTA_FAILURE
            raise

    def _raise_if_optimistic(
        self, response: SchemaBeaconAPI.ExecutionOptimisticResponse
    ) -> None:
        if response.execution_optimistic:
            raise ValueError(f"Execution optimistic on {self.host}")

    async def get_genesis(self) -> Genesis:
        resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/beacon/genesis",
        )
        return Genesis.from_obj(json.loads(resp)["data"])

    async def get_spec(self) -> Spec:
        resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/config/spec",
        )

        return parse_spec(json.loads(resp)["data"])

    async def get_node_version(self) -> None:
        resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/node/version",
        )

        try:
            version = json.loads(resp)["data"]["version"]
        except Exception as e:
            self.logger.warning(f"Failed to parse beacon node version: {e}")
            version = "unknown"

        _BEACON_NODE_VERSION.labels(host=self.host, version=version).set(1)
        return version

    async def produce_attestation_data(
        self, slot: int, committee_index: int
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
                    connect=self.client_session.timeout.connect, total=0.3
                ),
            )

            att_data = AttestationData.from_obj(json.loads(resp)["data"])
            tracer_span.add_event(
                "AttestationData",
                attributes={
                    "att_data.beacon_block_root": att_data.beacon_block_root.to_obj(),
                },
            )
            return att_data

    async def wait_for_attestation_data(
        self, expected_head_block_root: str, slot: int, committee_index: int
    ) -> AttestationData:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.wait_for_attestation_data",
            attributes={
                "server.address": self.host,
            },
        ):
            while True:
                _request_start_time = asyncio.get_event_loop().time()

                try:
                    att_data = await self.produce_attestation_data(
                        slot=slot,
                        committee_index=committee_index,
                    )
                    if att_data.beacon_block_root.to_obj() == expected_head_block_root:
                        return att_data
                except Exception as e:
                    self.logger.exception(e)

                # Rate-limiting - wait at least 50ms in between requests
                elapsed_time = asyncio.get_event_loop().time() - _request_start_time
                await asyncio.sleep(max(0.05 - elapsed_time, 0))

    async def get_block_root(self, block_id: str | int) -> str:
        resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/beacon/blocks/{block_id}/root",
            formatted_endpoint_string_params=dict(block_id=block_id),
            timeout=ClientTimeout(
                connect=self.client_session.timeout.connect,
                total=2 * self.client_session.timeout.connect,
            ),
        )

        response = SchemaBeaconAPI.GetBlockRootResponse.model_validate_json(resp)
        self._raise_if_optimistic(response)

        return response.data.root

    async def _get_validators_fallback(
        self,
        ids: list[str],
        statuses: list[SchemaValidator.ValidatorStatus],
        state_id: str = "head",
    ) -> list[SchemaValidator.ValidatorIndexPubkey]:
        if len(ids) == 0:
            return []

        _endpoint = "/eth/v1/beacon/states/{state_id}/validators"

        _BATCH_SIZE = 64

        results = []
        for i in range(0, len(ids), _BATCH_SIZE):
            ids_batch = ids[i : i + _BATCH_SIZE]

            resp = await self._make_request(
                method="GET",
                endpoint=_endpoint,
                formatted_endpoint_string_params=dict(state_id=state_id),
                params={
                    "id": ids_batch,
                    "status": [s.value for s in statuses],
                },
            )

            results += [
                SchemaValidator.ValidatorIndexPubkey(
                    index=v["index"],
                    pubkey=v["validator"]["pubkey"],
                    status=v["status"],
                )
                for v in json.loads(resp)["data"]
            ]
        return results

    async def get_validators(
        self,
        ids: list[str],
        statuses: list[SchemaValidator.ValidatorStatus],
        state_id: str = "head",
    ) -> list[SchemaValidator.ValidatorIndexPubkey]:
        if len(ids) == 0:
            return []

        try:
            resp = await self._make_request(
                method="POST",
                endpoint="/eth/v1/beacon/states/{state_id}/validators",
                formatted_endpoint_string_params=dict(state_id=state_id),
                json={
                    "ids": ids,
                    "statuses": [s.value for s in statuses],
                },
            )
        except BeaconNodeUnsupportedEndpoint:
            # Grandine doesn't support the POST endpoint yet
            # -> fall back to GET endpoint
            return await self._get_validators_fallback(
                ids=ids, statuses=statuses, state_id=state_id
            )

        return [
            SchemaValidator.ValidatorIndexPubkey(
                index=v["index"], pubkey=v["validator"]["pubkey"], status=v["status"]
            )
            for v in json.loads(resp)["data"]
        ]

    async def get_attester_duties(
        self, epoch: int, indices: list[int]
    ) -> SchemaBeaconAPI.GetAttesterDutiesResponse:
        resp = await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/duties/attester/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
            json=[str(i) for i in indices],
        )

        response = SchemaBeaconAPI.GetAttesterDutiesResponse.model_validate_json(resp)
        self._raise_if_optimistic(response)

        return response

    async def get_proposer_duties(
        self, epoch: int
    ) -> SchemaBeaconAPI.GetProposerDutiesResponse:
        resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/validator/duties/proposer/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
        )

        response = SchemaBeaconAPI.GetProposerDutiesResponse.model_validate_json(resp)
        self._raise_if_optimistic(response)

        return response

    async def get_sync_duties(
        self, epoch: int, indices: list[int]
    ) -> SchemaBeaconAPI.GetSyncDutiesResponse:
        resp = await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/duties/sync/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
            json=[str(i) for i in indices],
        )
        response = SchemaBeaconAPI.GetSyncDutiesResponse.model_validate_json(resp)
        self._raise_if_optimistic(response)

        return response

    async def publish_sync_committee_messages(self, messages: list[dict]) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/beacon/pool/sync_committees",
            json=messages,
        )

    async def publish_attestations(self, attestations: list[dict]) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/beacon/pool/attestations",
            json=attestations,
        )

    async def prepare_beacon_committee_subscriptions(self, data: list[dict]) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/beacon_committee_subscriptions",
            json=data,
        )

    async def prepare_sync_committee_subscriptions(self, data: list[dict]) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/sync_committee_subscriptions",
            json=data,
        )

    async def get_aggregate_attestation(
        self, attestation_data: AttestationData
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

        return Attestation.from_obj(json.loads(resp)["data"])

    async def publish_aggregate_and_proofs(
        self, signed_aggregate_and_proofs: list[tuple[dict, str]]
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/aggregate_and_proofs",
            json=[
                dict(message=msg, signature=sig)
                for msg, sig in signed_aggregate_and_proofs
            ],
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
            json.loads(resp)["data"]
        )

    async def publish_sync_committee_contribution_and_proofs(
        self,
        signed_contribution_and_proofs: list[tuple[dict, str]],
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/contribution_and_proofs",
            json=[
                dict(message=contribution, signature=sig)
                for contribution, sig in signed_contribution_and_proofs
            ],
        )

    async def prepare_beacon_proposer(self, data: list[dict[str, str]]) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/prepare_beacon_proposer",
            json=data,
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
            json=[
                dict(message=registration.model_dump(), signature=sig)
                for registration, sig in signed_registrations
            ],
        )

    async def produce_block_v3(
        self,
        slot: int,
        graffiti: bytes,
        builder_boost_factor: int,
        randao_reveal: str,
    ) -> SchemaBeaconAPI.ProduceBlockV3Response:
        """
        Requests a beacon node to produce a valid block, which can then be signed by a validator.
        The returned block may be blinded or unblinded, depending on the current state of the network
        as decided by the execution and beacon nodes.

        The beacon node must return an unblinded block if it obtains the execution payload from
        its paired execution node. It must only return a blinded block if it obtains the execution
        payload header from an MEV relay.

        Metadata in the response indicates the type of block produced, and the supported types
        of blocks will be extended to as forks progress.
        """
        params = dict(
            randao_reveal=randao_reveal, builder_boost_factor=str(builder_boost_factor)
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

            response = SchemaBeaconAPI.ProduceBlockV3Response.model_validate_json(resp)

            tracer_span.add_event(
                "ProduceBlockV3Response",
                attributes=dict(
                    blinded=response.execution_payload_blinded,
                    execution_payload_value=response.execution_payload_value,
                    consensus_block_value=response.consensus_block_value,
                ),
            )
            return response

    async def publish_block_v2(
        self,
        block_version: SchemaBeaconAPI.BeaconBlockVersion,
        block: Container,
        blobs: list,
        kzg_proofs: list,
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
            f" body root {block.body.hash_tree_root().hex()}"
        )

        await self._make_request(
            method="POST",
            endpoint="/eth/v2/beacon/blocks",
            json=data,
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
            f" body root {block.body.hash_tree_root().hex()}"
        )

        await self._make_request(
            method="POST",
            endpoint="/eth/v2/beacon/blinded_blocks",
            json=data,
            headers={"Eth-Consensus-Version": block_version.value},
        )

    async def subscribe_to_events(
        self, topics: list[str]
    ) -> AsyncIterable[SchemaBeaconAPI.BeaconNodeEvent]:
        async with self.client_session.get(
            url=self.base_url.join(URL("/eth/v1/events")),
            params={"topics": topics},
            headers={"accept": "text/event-stream"},
            timeout=ClientTimeout(total=None),  # Defaults to 5 minutes
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
                        f"Unexpected message from beacon node: {repr(decoded)}"
                    )
                    continue

                try:
                    event_name = decoded.split(":")[1].strip()
                except Exception:
                    self.logger.error(
                        f"Failed to parse event name from {decoded} -> ignoring event..."
                    )
                    continue
                event_data = []
                next_line = (await anext(events_iter)).decode()
                while next_line not in ("\n", "\r\n"):
                    event_data.append(next_line)
                    next_line = (await anext(events_iter)).decode()

                if event_name == "head":
                    yield SchemaBeaconAPI.HeadEvent.model_validate_json(
                        (event_data[0].split("data:")[1])
                    )
                elif event_name == "chain_reorg":
                    yield SchemaBeaconAPI.ChainReorgEvent.model_validate_json(
                        (event_data[0].split("data:")[1])
                    )
                elif event_name == "attester_slashing":
                    yield SchemaBeaconAPI.AttesterSlashingEvent.model_validate_json(
                        (event_data[0].split("data:")[1])
                    )
                elif event_name == "proposer_slashing":
                    yield SchemaBeaconAPI.ProposerSlashingEvent.model_validate_json(
                        (event_data[0].split("data:")[1])
                    )
                else:
                    raise NotImplementedError(
                        f"Unable to process event with name {event_name}, event_data {event_data}!"
                    )
