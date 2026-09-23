"""Provides methods for interacting with a beacon node through the [Beacon Node API](https://github.com/ethereum/beacon-APIs)."""

import asyncio
import contextlib
import datetime
import warnings
from collections.abc import AsyncIterable
from dataclasses import fields
from typing import TYPE_CHECKING, Literal, Self, Unpack, cast

import msgspec
from aiohttp import ClientResponse, ClientTimeout
from aiohttp.client import _RequestOptions
from aiohttp.hdrs import ACCEPT, CONTENT_TYPE
from opentelemetry.trace import SpanKind
from spy_ssz import (
    ExecutionPayloadEnvelopeGloas,
    Fork,
    ObjectKind,
    Preset,
    get_ssz_type,
)
from yarl import URL

from observability import (
    ErrorType,
)
from observability.api_client import ServiceType
from providers._headers import (
    ETH_BLOB_DATA_INCLUDED,
    ETH_CONSENSUS_BLOCK_VALUE,
    ETH_CONSENSUS_VERSION,
    ETH_EXECUTION_PAYLOAD_BLINDED,
    ETH_EXECUTION_PAYLOAD_INCLUDED,
    ETH_EXECUTION_PAYLOAD_VALUE,
    ContentType,
)
from schemas import (
    SchemaBeaconAPI,
    SchemaRemoteSigner,
    SchemaShared,
    SchemaValidator,
)
from schemas.beacon_api import is_optimistic
from spec import (
    Attestation,
    AttestationData,
    Checkpoint,
    PayloadAttestationData,
    SyncCommitteeContribution,
    preset_types,
)
from spec.base import SpecGloas, parse_spec
from spec.common import get_slot_component_duration_ms

from ._api_client import ApiClient

if TYPE_CHECKING:
    from .vero import Vero

_TIMEOUT_DEFAULT_SOCK_CONNECT = 1
_TIMEOUT_DEFAULT_TOTAL = 10
_MAX_SSE_EVENT_BYTES = 16 * 2**20  # 16 MiB


class BeaconNodeNotReady(Exception):
    pass


class BeaconNodeUnsupportedEndpoint(Exception):
    pass


class BadRequest(Exception):
    pass


class BeaconNode(ApiClient):
    MAX_SCORE = 100
    SCORE_DELTA_SUCCESS = 1
    SCORE_DELTA_FAILURE = 5

    def __init__(
        self,
        base_url: str,
        vero: "Vero",
    ) -> None:
        super().__init__(
            base_url=base_url,
            metrics=vero.metrics,
            service_type=ServiceType.BEACON_NODE,
            timeout=ClientTimeout(
                sock_connect=_TIMEOUT_DEFAULT_SOCK_CONNECT,
                total=_TIMEOUT_DEFAULT_TOTAL,
            ),
        )

        self.spec = vero.spec
        self._timeout_request_aggregate = (
            int(self.spec.SLOT_DURATION_MS)
            - get_slot_component_duration_ms(
                basis_points=self.spec.AGGREGATE_DUE_BPS,
                slot_duration_ms=self.spec.SLOT_DURATION_MS,
            )
        ) / 1_000
        self._timeout_request_contribution = (
            int(self.spec.SLOT_DURATION_MS)
            - get_slot_component_duration_ms(
                basis_points=self.spec.CONTRIBUTION_DUE_BPS,
                slot_duration_ms=self.spec.SLOT_DURATION_MS,
            )
        ) / 1_000
        self._ignore_spec_mismatch = vero.cli_args.ignore_spec_mismatch
        self._force_json_wire_format = vero.cli_args.force_json_wire_format

        self.scheduler = vero.scheduler
        self.task_manager = vero.task_manager

        self.initialized = False
        self._init_retry_interval = 5.0
        self._score = 0
        self.metrics.beacon_node_score_g.labels(netloc=self.netloc).set(0)
        self.metrics.checkpoint_confirmations_c.labels(netloc=self.netloc).reset()
        self.node_version = ""

        self._trace_default_request_ctx = dict(
            netloc=self.netloc,
            service_type=ServiceType.BEACON_NODE.value,
        )

        self.json_encoder = msgspec.json.Encoder()

    def _fork_for_slot(self, slot: int) -> Fork:
        epoch = slot // int(self.spec.SLOTS_PER_EPOCH)
        if epoch >= int(self.spec.GLOAS_FORK_EPOCH):
            return Fork.GLOAS
        if epoch >= int(self.spec.FULU_FORK_EPOCH):
            return Fork.FULU
        if epoch >= int(self.spec.ELECTRA_FORK_EPOCH):
            return Fork.ELECTRA
        raise NotImplementedError(f"Unsupported fork for {epoch=}")

    @property
    def score(self) -> int:
        return self._score

    @score.setter
    def score(self, value: int) -> None:
        self._score = max(0, min(value, BeaconNode.MAX_SCORE))
        self.metrics.beacon_node_score_g.labels(netloc=self.netloc).set(self._score)

    async def _initialize_full(self) -> None:
        # Raise if the spec returned by the beacon node differs
        bn_spec = await self.get_spec()
        if self.spec != bn_spec and not self._ignore_spec_mismatch:
            msg = f"Spec values returned by beacon node {self.netloc} not equal to hardcoded spec values. Use the `--ignore-spec-mismatch` flag to ignore this error."
            for field in fields(self.spec):
                if getattr(self.spec, field.name) != getattr(bn_spec, field.name):
                    msg += (
                        f"\n{field.name}:"
                        f"\n\tIncluded value: {getattr(self.spec, field.name)}"
                        f"\n\tValue returned by beacon node: {getattr(bn_spec, field.name)}"
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
    async def _raise_for_status(response: ClientResponse) -> None:
        try:
            await ApiClient._raise_for_status(response)
        except ValueError:
            resp_text = await ApiClient._read_error_text(response)
            exc_map = {
                503: BeaconNodeNotReady,
                405: BeaconNodeUnsupportedEndpoint,
                400: BadRequest,
            }
            if response.status in exc_map:
                raise exc_map[response.status](
                    response.request_info.url, resp_text
                ) from None
            raise

    async def _make_request(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        formatted_endpoint_string_params: dict[str, str | int] | None = None,
        **kwargs: Unpack[_RequestOptions],
    ) -> tuple[bytes, str | None, ClientResponse]:
        try:
            resp_tuple = await super().make_request(
                method=method,
                endpoint=endpoint,
                formatted_endpoint_string_params=formatted_endpoint_string_params,
                raise_for_status=self._raise_for_status,
                **kwargs,
            )
        except BeaconNodeNotReady:
            self.score -= BeaconNode.SCORE_DELTA_FAILURE
            raise
        except Exception as e:
            self.logger.debug(
                f"Failed to get response from {self.netloc} for {method} {endpoint}: {e!r}",
            )
            self.score -= BeaconNode.SCORE_DELTA_FAILURE
            raise
        else:
            # Request was successfully fulfilled
            self.score += BeaconNode.SCORE_DELTA_SUCCESS
            return resp_tuple

    def _raise_if_optimistic(
        self,
        response: SchemaBeaconAPI.ExecutionOptimisticResponse
        | SchemaBeaconAPI.BeaconNodeEvent,
    ) -> None:
        if is_optimistic(response):
            raise ValueError(f"Execution optimistic on {self.netloc}")

    async def get_spec(self) -> SpecGloas:
        resp_bytes, _, _ = await self._make_request(
            method="GET",
            endpoint="/eth/v1/config/spec",
        )

        return parse_spec(msgspec.json.decode(resp_bytes)["data"])

    async def update_node_version(self) -> None:
        resp_bytes, _, _ = await self._make_request(
            method="GET",
            endpoint="/eth/v1/node/version",
        )

        try:
            resp_version = msgspec.json.decode(resp_bytes)["data"]["version"]
        except Exception as e:
            self.logger.warning(f"Failed to parse beacon node version: {e}")
            resp_version = "unknown"

        if not isinstance(resp_version, str):
            raise TypeError(
                f"Beacon node did not return a string version: {type(resp_version)} : {resp_version}",
            )

        if resp_version != self.node_version:
            self.logger.info(
                f"Beacon node version changed on {self.netloc}: {self.node_version} -> {resp_version}"
            )
            # Remove old metric value in order not to report multiple values
            # for the same netloc
            with contextlib.suppress(KeyError), warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.metrics.beacon_node_version_g.remove(
                    self.netloc, self.node_version
                )

        self.node_version = resp_version
        self.metrics.beacon_node_version_g.labels(
            netloc=self.netloc, version=self.node_version
        ).set(1)

    async def produce_attestation_data(
        self,
        slot: int,
    ) -> tuple[str, AttestationData]:
        """Returns the beacon node netloc along with the produced attestation data."""
        resp_bytes, _, _ = await self._make_request(
            method="GET",
            endpoint="/eth/v1/validator/attestation_data",
            params=dict(
                slot=slot,
                committee_index=0,
            ),
            timeout=ClientTimeout(
                sock_connect=self.client_session.timeout.sock_connect,
                total=0.5,
            ),
        )

        response = msgspec.json.decode(resp_bytes, type=SchemaBeaconAPI.RawDataResponse)
        return (
            self.netloc,
            preset_types(self._fork_for_slot(slot)).attestation_data.from_json(
                response.data
            ),
        )

    async def wait_for_attestation_data(
        self,
        expected_head_block_root: str,
        slot: int,
    ) -> AttestationData:
        while True:
            _request_start_time = asyncio.get_running_loop().time()

            try:
                _, att_data = await self.produce_attestation_data(
                    slot=slot,
                )
                if f"0x{att_data.beacon_block_root.hex()}" == expected_head_block_root:
                    self.logger.debug(
                        f"Got matching AttestationData from {self.netloc}"
                    )
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
        expected_source_cp: Checkpoint,
        expected_target_cp: Checkpoint,
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
                    self.logger.info(f"Finality checkpoints confirmed by {self.netloc}")
                    self.metrics.checkpoint_confirmations_c.labels(
                        netloc=self.netloc
                    ).inc()
                    return
            except Exception as e:
                self.logger.warning(
                    f"Failed to produce attestation data while waiting for checkpoints: {e!r}",
                )

            # Rate-limiting - wait at least 50ms in between requests
            elapsed_time = asyncio.get_running_loop().time() - _request_start_time
            await asyncio.sleep(max(0.05 - elapsed_time, 0))

    async def get_block_root(self, block_id: str) -> str:
        resp_bytes, _, _ = await self._make_request(
            method="GET",
            endpoint="/eth/v1/beacon/blocks/{block_id}/root",
            formatted_endpoint_string_params=dict(block_id=block_id),
            timeout=ClientTimeout(
                sock_connect=self.client_session.timeout.sock_connect,
                total=1,
            ),
        )

        response = msgspec.json.decode(
            resp_bytes, type=SchemaBeaconAPI.GetBlockRootResponse
        )
        self._raise_if_optimistic(response)

        return response.data.root

    async def get_validators(
        self,
        request_data: bytes,
        state_id: str = "head",
    ) -> list[SchemaValidator.ValidatorIndexPubkey]:
        resp_bytes, _, _ = await self._make_request(
            method="POST",
            endpoint="/eth/v1/beacon/states/{state_id}/validators",
            formatted_endpoint_string_params=dict(state_id=state_id),
            data=request_data,
        )

        resp_decoded = msgspec.json.decode(
            resp_bytes, type=SchemaBeaconAPI.GetStateValidatorsResponse
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
        resp_bytes, _, _ = await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/duties/attester/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
            data=self.json_encoder.encode([str(i) for i in indices]),
        )

        response = msgspec.json.decode(
            resp_bytes, type=SchemaBeaconAPI.GetAttesterDutiesResponse
        )
        self._raise_if_optimistic(response)

        return response

    async def get_proposer_duties(
        self,
        epoch: int,
    ) -> SchemaBeaconAPI.GetProposerDutiesResponse:
        resp_bytes, _, _ = await self._make_request(
            method="GET",
            endpoint="/eth/v1/validator/duties/proposer/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
        )

        response = msgspec.json.decode(
            resp_bytes, type=SchemaBeaconAPI.GetProposerDutiesResponse
        )
        self._raise_if_optimistic(response)

        return response

    async def get_proposer_duties_v2(
        self,
        epoch: int,
    ) -> SchemaBeaconAPI.GetProposerDutiesResponse:
        resp_bytes, _, _ = await self._make_request(
            method="GET",
            endpoint="/eth/v2/validator/duties/proposer/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
        )

        response = msgspec.json.decode(
            resp_bytes, type=SchemaBeaconAPI.GetProposerDutiesResponse
        )
        self._raise_if_optimistic(response)

        return response

    async def get_sync_duties(
        self,
        epoch: int,
        indices: list[int],
    ) -> SchemaBeaconAPI.GetSyncDutiesResponse:
        resp_bytes, _, _ = await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/duties/sync/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
            data=self.json_encoder.encode([str(i) for i in indices]),
        )
        response = msgspec.json.decode(
            resp_bytes, type=SchemaBeaconAPI.GetSyncDutiesResponse
        )
        self._raise_if_optimistic(response)

        return response

    async def get_ptc_duties(
        self,
        epoch: int,
        indices: list[int],
    ) -> SchemaBeaconAPI.GetPtcDutiesResponse:
        resp_bytes, _, _ = await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/duties/ptc/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
            data=self.json_encoder.encode([str(i) for i in indices]),
        )

        response = msgspec.json.decode(
            resp_bytes, type=SchemaBeaconAPI.GetPtcDutiesResponse
        )
        self._raise_if_optimistic(response)

        return response

    async def publish_sync_committee_messages(
        self,
        encoded_messages: bytes,
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/beacon/pool/sync_committees",
            data=encoded_messages,
        )

    async def publish_attestations(
        self,
        encoded_attestations: bytes,
        fork_version: SchemaShared.ForkVersion,
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v2/beacon/pool/attestations",
            data=encoded_attestations,
            headers={ETH_CONSENSUS_VERSION: fork_version.value},
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
    ) -> Attestation:
        resp_bytes, _, _ = await self._make_request(
            method="GET",
            endpoint="/eth/v2/validator/aggregate_attestation",
            params=dict(
                attestation_data_root=attestation_data_root,
                slot=slot,
                committee_index=committee_index,
            ),
            timeout=ClientTimeout(
                sock_connect=self.client_session.timeout.sock_connect,
                total=self._timeout_request_aggregate,
            ),
        )

        response = msgspec.json.decode(
            resp_bytes, type=SchemaBeaconAPI.GetAggregatedAttestationV2Response
        )

        att = preset_types(self._fork_for_slot(slot)).attestation.from_json(
            response.data
        )

        self.metrics.beacon_node_aggregate_attestation_participant_count_h.labels(
            netloc=self.netloc
        ).observe(sum(att.aggregation_bits))
        return att

    async def publish_aggregate_and_proofs(
        self,
        encoded_signed_aggregate_and_proofs: bytes,
        fork_version: SchemaShared.ForkVersion,
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v2/validator/aggregate_and_proofs",
            data=encoded_signed_aggregate_and_proofs,
            headers={ETH_CONSENSUS_VERSION: fork_version.value},
        )

    async def get_sync_committee_contribution(
        self,
        slot: int,
        subcommittee_index: int,
        beacon_block_root: str,
    ) -> SyncCommitteeContribution:
        resp_bytes, _, _ = await self._make_request(
            method="GET",
            endpoint="/eth/v1/validator/sync_committee_contribution",
            params=dict(
                slot=slot,
                subcommittee_index=subcommittee_index,
                beacon_block_root=beacon_block_root,
            ),
            timeout=ClientTimeout(
                sock_connect=self.client_session.timeout.sock_connect,
                total=self._timeout_request_contribution,
            ),
        )

        response = msgspec.json.decode(resp_bytes, type=SchemaBeaconAPI.RawDataResponse)
        contribution = preset_types(
            self._fork_for_slot(slot)
        ).sync_committee_contribution.from_json(response.data)
        self.metrics.beacon_node_sync_contribution_participant_count_h.labels(
            netloc=self.netloc
        ).observe(sum(contribution.aggregation_bits))
        return contribution

    async def publish_sync_committee_contribution_and_proofs(
        self,
        encoded_signed_contribution_and_proofs: bytes,
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/contribution_and_proofs",
            data=encoded_signed_contribution_and_proofs,
        )

    async def produce_payload_attestation_data(
        self,
        slot: int,
    ) -> PayloadAttestationData | None:
        resp_bytes, _, resp = await self._make_request(
            method="GET",
            endpoint="/eth/v1/validator/payload_attestation_data",
            params=dict(slot=slot),
        )
        if resp.status == 204:
            # No block has been seen for the requested slot.
            # Used to signal validator to not cast any payload attestation.
            return None

        response = msgspec.json.decode(resp_bytes, type=SchemaBeaconAPI.RawDataResponse)
        return preset_types(
            self._fork_for_slot(slot)
        ).payload_attestation_data.from_json(response.data)

    async def publish_payload_attestation_messages(
        self,
        encoded_messages: bytes,
        fork_version: SchemaShared.ForkVersion,
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/beacon/pool/payload_attestations",
            data=encoded_messages,
            headers={ETH_CONSENSUS_VERSION: fork_version.value},
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

    async def submit_proposer_preferences(
        self,
        signed_proposer_preferences: list[
            tuple[SchemaRemoteSigner.ProposerPreferences, str]
        ],
        fork_version: SchemaShared.ForkVersion,
    ) -> None:
        await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/proposer_preferences",
            headers={ETH_CONSENSUS_VERSION: fork_version.value},
            data=self.json_encoder.encode(
                [
                    dict(message=preferences, signature=sig)
                    for preferences, sig in signed_proposer_preferences
                ]
            ),
        )

    async def produce_block_v3(
        self,
        slot: int,
        graffiti: bytes,
        builder_boost_factor: str,
        randao_reveal: str,
    ) -> tuple[SchemaBeaconAPI.ProduceBlockV3Response, ContentType, Self]:
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
            builder_boost_factor=builder_boost_factor,
        )
        if graffiti:
            params["graffiti"] = f"0x{graffiti.hex()}"

        accept_header = (
            ContentType.JSON.value
            if self._force_json_wire_format
            # Prefer SSZ over JSON
            else f"{ContentType.OCTET_STREAM.value};q=1.0,{ContentType.JSON.value};q=0.9"
        )

        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.produce_block_v3",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": self.netloc,
            },
        ) as tracer_span:
            resp_bytes, content_type, resp = await self._make_request(
                method="GET",
                endpoint="/eth/v3/validator/blocks/{slot}",
                formatted_endpoint_string_params=dict(slot=slot),
                params=params,
                timeout=ClientTimeout(
                    sock_connect=self.client_session.timeout.sock_connect,
                ),
                headers={ACCEPT: accept_header},
            )
            if (
                content_type == ContentType.JSON.value
                and not self._force_json_wire_format
            ):
                self.logger.warning(
                    f"{self.netloc} returned block as JSON but Vero requested SSZ"
                )

            try:
                response_content_type = ContentType(content_type)
            except ValueError:
                raise NotImplementedError(
                    f"Unsupported content type: {content_type}"
                ) from None

            response = SchemaBeaconAPI.ProduceBlockV3Response(
                version=SchemaShared.ForkVersion(resp.headers[ETH_CONSENSUS_VERSION]),
                execution_payload_blinded=resp.headers[
                    ETH_EXECUTION_PAYLOAD_BLINDED
                ].lower()
                == "true",
                execution_payload_value=resp.headers[ETH_EXECUTION_PAYLOAD_VALUE],
                consensus_block_value=resp.headers[ETH_CONSENSUS_BLOCK_VALUE],
                data=resp_bytes,
            )

            # Prysm may return an empty string for the block value
            # https://github.com/OffchainLabs/prysm/issues/15174
            execution_payload_value_int = int(response.execution_payload_value or 0)
            consensus_block_value_int = int(response.consensus_block_value or 0)
            response.execution_payload_value = str(execution_payload_value_int)
            response.consensus_block_value = str(consensus_block_value_int)

            tracer_span.add_event(
                "ProduceBlockV3Response",
                attributes=dict(
                    blinded=response.execution_payload_blinded,
                    execution_payload_value=execution_payload_value_int,
                    consensus_block_value=consensus_block_value_int,
                ),
            )

            self.logger.info(
                f"{self.netloc} returned block with"
                f" consensus block value {consensus_block_value_int:,},"
                f" execution payload value {execution_payload_value_int:,}."
            )
            self.metrics.beacon_node_consensus_block_value_h.labels(
                netloc=self.netloc
            ).observe(consensus_block_value_int)
            self.metrics.beacon_node_execution_payload_value_h.labels(
                netloc=self.netloc
            ).observe(execution_payload_value_int)

            return response, response_content_type, self

    async def produce_block_v4(
        self,
        slot: int,
        graffiti: bytes,
        builder_config: SchemaBeaconAPI.BuilderConfig,
        randao_reveal: str,
        signed_payload_bid: SchemaShared.SignedExecutionPayloadBid | None,
        fork_version: SchemaShared.ForkVersion,
    ) -> tuple[SchemaBeaconAPI.ProduceBlockV4Response, ContentType, Self]:
        """Requests a beacon node to produce a valid block, which can then be signed by a validator."""
        # TODO deduplicate with produce_block_v3, it's near to a copy-paste
        # Keep the stateful self-build flow: Lodestar caches the payload envelope,
        # which Vero retrieves after publishing the beacon block.
        # TODO support stateless self-build flow?
        include_payload = False
        params = dict(
            randao_reveal=randao_reveal,
            builder_boost_factor=builder_config.builder_boost_factor,
            include_payload=str(include_payload).lower(),
        )
        if graffiti:
            params["graffiti"] = f"0x{graffiti.hex()}"

        # TODO BYOB not yet implemented - possibly in separate endpoint!
        _endpoint = "/eth/v4/validator/blocks/{slot}"
        request_body: (
            SchemaShared.SignedExecutionPayloadBid | SchemaBeaconAPI.BuilderConfig
        )
        if signed_payload_bid:
            # use separate produceBlockV4WithBid endpoint
            _endpoint += "/with_bid"
            params["builder_boost_factor"] = builder_config.builder_boost_factor
            self.logger.info(
                f"Setting body for block production, bid: {signed_payload_bid}"
            )
            # actually we might want to do all this in MultiBeaconNode already...
            # at least the "expensive" encoding of the body, just do it once
            request_body = signed_payload_bid
        else:
            request_body = builder_config
        data = self.json_encoder.encode(request_body)

        accept_header = (
            ContentType.JSON.value
            if self._force_json_wire_format
            # Prefer SSZ over JSON
            else f"{ContentType.OCTET_STREAM.value};q=1.0,{ContentType.JSON.value};q=0.9"
        )

        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.produce_block_v4",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": self.netloc,
            },
        ) as tracer_span:
            resp_bytes, content_type, resp = await self._make_request(
                method="POST",
                endpoint=_endpoint,
                formatted_endpoint_string_params=dict(slot=slot),
                params=params,
                data=data,
                timeout=ClientTimeout(
                    sock_connect=self.client_session.timeout.sock_connect,
                ),
                headers={
                    ACCEPT: accept_header,
                    ETH_CONSENSUS_VERSION: fork_version.value,
                },
            )
            if (
                content_type == ContentType.JSON.value
                and not self._force_json_wire_format
            ):
                self.logger.warning(
                    f"{self.netloc} returned block as JSON but Vero requested SSZ"
                )

            try:
                response_content_type = ContentType(content_type)
            except ValueError:
                raise NotImplementedError(
                    f"Unsupported content type: {content_type}"
                ) from None

            execution_payload_included = (
                resp.headers[ETH_EXECUTION_PAYLOAD_INCLUDED].lower() == "true"
            )
            if include_payload != execution_payload_included:
                self.logger.warning(
                    f"Block requested with {include_payload=} but"
                    f" {self.netloc} returned {execution_payload_included=}."
                )

            response = SchemaBeaconAPI.ProduceBlockV4Response(
                version=SchemaShared.ForkVersion(resp.headers[ETH_CONSENSUS_VERSION]),
                execution_payload_included=execution_payload_included,
                execution_payload_value=resp.headers[ETH_EXECUTION_PAYLOAD_VALUE],
                consensus_block_value=resp.headers[ETH_CONSENSUS_BLOCK_VALUE],
                data=resp_bytes,
            )

            # Prysm may return an empty string for the block value
            # https://github.com/OffchainLabs/prysm/issues/15174
            execution_payload_value_int = int(response.execution_payload_value or 0)
            consensus_block_value_int = int(response.consensus_block_value or 0)
            response.execution_payload_value = str(execution_payload_value_int)
            response.consensus_block_value = str(consensus_block_value_int)

            tracer_span.add_event(
                "ProduceBlockV4Response",
                attributes=dict(
                    execution_payload_included=response.execution_payload_included,
                    execution_payload_value=execution_payload_value_int,
                    consensus_block_value=consensus_block_value_int,
                ),
            )

            # TODO do something else/more here?
            #  also we only need this in the BYOB endpoint
            if (
                signed_payload_bid
                and signed_payload_bid.total_value_wei != execution_payload_value_int
            ):
                self.logger.warning(
                    f"Mismatch between supplied bid and execution payload value: {signed_payload_bid.total_value_wei:,} != {execution_payload_value_int:,}"
                )

            self.logger.info(
                f"{self.netloc} returned block with"
                f" consensus block value {consensus_block_value_int:,},"
                f" execution payload value {execution_payload_value_int:,}."
            )
            self.metrics.beacon_node_consensus_block_value_h.labels(
                netloc=self.netloc
            ).observe(consensus_block_value_int)
            self.metrics.beacon_node_execution_payload_value_h.labels(
                netloc=self.netloc
            ).observe(execution_payload_value_int)

            return response, response_content_type, self

    async def publish_block_v2(
        self,
        fork_version: SchemaShared.ForkVersion,
        signed_block_contents: bytes,
        content_type: ContentType,
    ) -> None:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.publish_block_v2",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": self.netloc,
            },
        ):
            await self._make_request(
                method="POST",
                endpoint="/eth/v2/beacon/blocks",
                data=signed_block_contents,
                headers={
                    ETH_CONSENSUS_VERSION: fork_version.value,
                    CONTENT_TYPE: content_type.value,
                },
            )

    async def publish_blinded_block_v2(
        self,
        fork_version: SchemaShared.ForkVersion,
        signed_blinded_beacon_block: bytes,
        content_type: ContentType,
    ) -> None:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.publish_blinded_block_v2",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": self.netloc,
            },
        ):
            _, _, _ = await self._make_request(
                method="POST",
                endpoint="/eth/v2/beacon/blinded_blocks",
                data=signed_blinded_beacon_block,
                headers={
                    ETH_CONSENSUS_VERSION: fork_version.value,
                    CONTENT_TYPE: content_type.value,
                },
            )

    async def get_execution_payload_envelope(
        self,
        slot: int,
        beacon_block_root: str,
    ) -> tuple[SchemaShared.ForkVersion, ExecutionPayloadEnvelopeGloas]:
        accept_header = (
            ContentType.JSON.value
            if self._force_json_wire_format
            # Prefer SSZ over JSON
            else f"{ContentType.OCTET_STREAM.value};q=1.0,{ContentType.JSON.value};q=0.9"
        )

        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.get_execution_payload_envelope",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": self.netloc,
            },
        ):
            resp_bytes, content_type, resp = await self._make_request(
                method="GET",
                endpoint="/eth/v1/validator/execution_payload_envelopes/{slot}/{beacon_block_root}",
                formatted_endpoint_string_params=dict(
                    slot=slot,
                    beacon_block_root=beacon_block_root,
                ),
                headers={ACCEPT: accept_header},
            )
            if (
                content_type == ContentType.JSON.value
                and not self._force_json_wire_format
            ):
                self.logger.warning(
                    f"{self.netloc} returned an execution payload envelope as JSON but Vero requested SSZ"
                )

            try:
                response_content_type = ContentType(content_type)
            except ValueError:
                raise NotImplementedError(
                    f"Unsupported content type: {content_type}"
                ) from None

            fork_version = SchemaShared.ForkVersion(resp.headers[ETH_CONSENSUS_VERSION])
            payload_cls = get_ssz_type(
                Fork[fork_version.name],
                ObjectKind.EXECUTION_PAYLOAD_ENVELOPE,
                Preset[preset_types().preset.upper()],
            )

            if response_content_type is ContentType.JSON:
                envelope = payload_cls.from_json(resp_bytes)
            elif response_content_type is ContentType.OCTET_STREAM:
                envelope = payload_cls.from_ssz(resp_bytes)
            else:
                raise NotImplementedError(
                    f"Unsupported content type: {response_content_type}"
                )
            return fork_version, cast("ExecutionPayloadEnvelopeGloas", envelope)

    async def publish_execution_payload_envelope(
        self,
        signed_execution_payload_envelope: bytes,
        fork_version: SchemaShared.ForkVersion,
        content_type: ContentType,
    ) -> None:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.publish_execution_payload_envelope",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": self.netloc,
            },
        ):
            _, _, _ = await self._make_request(
                method="POST",
                endpoint="/eth/v1/beacon/execution_payload_envelopes",
                headers={
                    ETH_CONSENSUS_VERSION: fork_version.value,
                    ETH_BLOB_DATA_INCLUDED: "false",
                    CONTENT_TYPE: content_type.value,
                },
                data=signed_execution_payload_envelope,
            )

    async def get_liveness(
        self, epoch: int, validator_indices: list[int]
    ) -> tuple[str, list[SchemaBeaconAPI.ValidatorLiveness]]:
        resp_bytes, _, _ = await self._make_request(
            method="POST",
            endpoint="/eth/v1/validator/liveness/{epoch}",
            formatted_endpoint_string_params=dict(epoch=epoch),
            timeout=ClientTimeout(
                sock_connect=self.client_session.timeout.sock_connect,
            ),
            data=self.json_encoder.encode([str(i) for i in validator_indices]),
        )

        return self.netloc, msgspec.json.decode(
            resp_bytes,
            type=SchemaBeaconAPI.PostLivenessResponseBody,
        ).data

    async def subscribe_to_events(
        self,
        topics: list[str],
    ) -> AsyncIterable[SchemaBeaconAPI.BeaconNodeEvent]:
        _event_name_to_struct_mapping: dict[
            str, type[SchemaBeaconAPI.BeaconNodeEvent]
        ] = dict(
            head_v2=SchemaBeaconAPI.HeadV2Event,
            execution_payload_available=SchemaBeaconAPI.ExecutionPayloadAvailableEvent,
            chain_reorg=SchemaBeaconAPI.ChainReorgEvent,
            attester_slashing=SchemaBeaconAPI.AttesterSlashingEvent,
            proposer_slashing=SchemaBeaconAPI.ProposerSlashingEvent,
            payload_attributes=SchemaBeaconAPI.PayloadAttributesEvent,
            execution_payload_bid=SchemaBeaconAPI.ExecutionPayloadBidEvent,
        )

        async with self.client_session.get(
            url=self.base_url.join(URL("/eth/v1/events")),
            params={"topics": topics},
            headers={"accept": "text/event-stream"},
            timeout=ClientTimeout(
                sock_connect=1, sock_read=None
            ),  # sock_read defaults to 5 minutes
        ) as resp:

            async def read_line() -> bytes:
                return await resp.content.readline(
                    max_line_length=2**20,  # 1 MiB
                )

            # Minimal SSE client implementation
            while True:
                line = await read_line()
                if not line:
                    break

                decoded = line.decode()
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
                    event_name = decoded.split(":", 1)[1].strip()
                except Exception as e:
                    self.metrics.errors_c.labels(
                        error_type=ErrorType.EVENT_CONSUMER.value,
                    ).inc()
                    self.logger.exception(
                        f"Failed to parse event name from {decoded} ({e!r}) "
                        "-> ignoring event...",
                    )
                    continue

                event_data = []
                event_data_bytes = 0

                while True:
                    line = await read_line()

                    if not line:
                        raise EOFError(
                            f"SSE stream ended while reading event {event_name}"
                        )

                    if line in (b"\n", b"\r\n"):
                        break

                    event_data_bytes += len(line)
                    if event_data_bytes > _MAX_SSE_EVENT_BYTES:
                        raise ValueError(
                            "Beacon node SSE event too large: "
                            f"more than {_MAX_SSE_EVENT_BYTES} bytes "
                            f"for event {event_name}"
                        )

                    event_data.append(line.decode())

                try:
                    event_struct = _event_name_to_struct_mapping[event_name]
                except KeyError:
                    raise NotImplementedError(
                        f"Unable to process event with name {event_name}, event_data: {event_data}!",
                    ) from None

                event = msgspec.json.decode(
                    event_data[0].split("data:")[1], type=event_struct
                )

                if is_optimistic(event):
                    raise ValueError(f"Execution optimistic for event: {event}")

                yield event
