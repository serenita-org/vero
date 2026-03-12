"""Uses multiple beacon nodes to provide the validator client with data.

The biggest advantage of using multiple beacon nodes is that we can
request attestation data from all of them, and only attest if enough
of them agree on the state of the chain, providing resilience against
single-client bugs.

This provider has 2 important internal methods:
1) `_get_first_beacon_node_response`

Requests a response from all beacon nodes and returns *the first* OK response.
This is used for retrieving validator status and similar requests
where it is not really important which beacon node we get a response from,
as long as it returns an OK status code (and execution is not optimistic).

2) `_get_all_beacon_node_responses`

Requests a response from all beacon nodes and returns *all* OK responses.
This is useful when there is an advantage to using all responses, e.g.

- submitting an aggregate attestation ( / sync committee contribution)
Here it can be advantageous to both the validator and the network at large to
submit the best aggregate - the one containing the most validator attestations.

- proposing a block
Here we can request all beacon nodes to produce a block, and publish the one with
the highest value.


Apart from these internal methods, the MultiBeaconNode provider has a property
called `best_beacon_node`. This can be used when we explicitly only want to
interact with a single beacon node - the one with the highest score. If all
connected beacon nodes have equal scores, the first beacon node will be used.
"""

import asyncio
import logging
import time
from collections import Counter
from collections.abc import AsyncIterator
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

from opentelemetry import trace
from remerkleable.complex import Container

from observability import ErrorType
from schemas import SchemaBeaconAPI, SchemaValidator
from spec import SpecAttestation, SpecBeaconBlock, SpecSyncCommittee
from spec.configs import Network

from .beacon_node import BeaconNode

if TYPE_CHECKING:
    from .vero import Vero


class MultiBeaconNode:
    def __init__(
        self,
        vero: "Vero",
        skip_init: bool = False,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.metrics = vero.metrics
        self.tracer = trace.get_tracer(self.__class__.__name__)

        self.beacon_nodes = [
            BeaconNode(
                base_url=base_url,
                vero=vero,
            )
            for base_url in vero.cli_args.beacon_node_urls
        ]
        self.beacon_nodes_proposal = [
            BeaconNode(
                base_url=base_url,
                vero=vero,
            )
            for base_url in vero.cli_args.beacon_node_urls_proposal
        ]

        self.cli_args = vero.cli_args

        self._attestation_consensus_threshold = (
            vero.cli_args.attestation_consensus_threshold
        )
        # On startup, wait for beacon nodes to initialize for 5 minutes
        # before raising an Exception.
        self._skip_init = skip_init
        self._init_timeout = 300

    async def initialize(self) -> None:
        if self._skip_init:
            for bn in self.beacon_nodes:
                bn.initialized = True
            return

        deadline = time.monotonic() + self._init_timeout

        def _init_error_message() -> str:
            return (
                "Failed to fully initialize a sufficient amount of beacon nodes - "
                f"{len(self.initialized_beacon_nodes)}/{len(self.beacon_nodes)} initialized "
                f"(required: {self._attestation_consensus_threshold})"
            )

        self.logger.info("Initializing beacon nodes")
        # Initialize the connected beacon nodes - retry logic is already present inside
        await asyncio.gather(*(bn.initialize_full() for bn in self.beacon_nodes))

        while (
            len(self.initialized_beacon_nodes) < self._attestation_consensus_threshold
        ):
            if time.monotonic() >= deadline:
                raise RuntimeError(_init_error_message())

            self.logger.debug(_init_error_message())
            await asyncio.sleep(0.1)

        # Check the connected beacon nodes spec
        if not len({bn.spec for bn in self.initialized_beacon_nodes}) == 1:
            raise RuntimeError(
                f"Beacon nodes provided different specs:"
                f" {[bn.spec for bn in self.initialized_beacon_nodes]}",
            )

        self.logger.info(
            f"Successfully initialized"
            f" {len(self.initialized_beacon_nodes)}"
            f"/{len(self.beacon_nodes)}"
            f" beacon nodes",
        )

    async def __aenter__(self) -> Self:
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        all_beacon_nodes = self.beacon_nodes + self.beacon_nodes_proposal

        await asyncio.gather(
            *[
                bn.client_session.close()
                for bn in all_beacon_nodes
                if not bn.client_session.closed
            ],
        )

    @property
    def best_beacon_node(self) -> BeaconNode:
        return next(
            bn
            for bn in sorted(
                self.initialized_beacon_nodes, key=lambda bn: bn.score, reverse=True
            )
        )

    @property
    def initialized_beacon_nodes(self) -> list[BeaconNode]:
        return [bn for bn in self.beacon_nodes if bn.initialized]

    async def _get_first_beacon_node_response(
        self,
        func_name: str,
        **kwargs: Any,
    ) -> Any:
        tasks = [
            asyncio.create_task(getattr(bn, func_name)(**kwargs))
            for bn in self.initialized_beacon_nodes
        ]

        for coro in asyncio.as_completed(tasks):
            try:
                resp = await coro
            except Exception as e:
                self.logger.warning(f"Failed to get a response from beacon node: {e!r}")
                continue
            else:
                # Successful response -> cancel other pending tasks
                for task in tasks:
                    task.cancel()
                return resp

        raise RuntimeError(
            f"Failed to get a response from all beacon nodes for {func_name}",
        )

    async def _get_all_beacon_node_responses(
        self,
        func_name: str,
        beacon_nodes: list[BeaconNode] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        # Returns a list of successful responses
        beacon_nodes_to_use = beacon_nodes or self.initialized_beacon_nodes

        responses: list[Any] = []
        for res in await asyncio.gather(
            *[getattr(bn, func_name)(**kwargs) for bn in beacon_nodes_to_use],
            return_exceptions=True,
        ):
            if isinstance(res, Exception):
                self.logger.warning(
                    f"Failed to get a response from beacon node: {res!r}"
                )
                continue

            responses.append(res)

        if len(responses) == 0:
            raise RuntimeError(
                f"Failed to get a response from all beacon nodes for {func_name}",
            )

        return responses

    async def get_validators(
        self,
        **kwargs: Any,
    ) -> list[SchemaValidator.ValidatorIndexPubkey]:
        resp: list[
            SchemaValidator.ValidatorIndexPubkey
        ] = await self._get_first_beacon_node_response(
            func_name="get_validators",
            **kwargs,
        )
        return resp

    async def get_proposer_duties(
        self,
        **kwargs: Any,
    ) -> SchemaBeaconAPI.GetProposerDutiesResponse:
        return await self.best_beacon_node.get_proposer_duties(**kwargs)

    async def prepare_beacon_proposer(self, **kwargs: Any) -> None:
        await self._get_all_beacon_node_responses(
            func_name="prepare_beacon_proposer",
            **kwargs,
        )

    async def register_validator(self, **kwargs: Any) -> None:
        # Only ask one of the beacon nodes to register the validators with
        # MEV relays - no need to overwhelm them with duplicate registrations
        await self.best_beacon_node.register_validator(**kwargs)

    @staticmethod
    def _parse_block_response(
        response: SchemaBeaconAPI.ProduceBlockV3Response,
    ) -> "SpecBeaconBlock.ElectraBlockContents | SpecBeaconBlock.ElectraBlindedBlock":
        # TODO perf
        #  profiling indicates this function takes a bit of time
        #  Maybe we don't need to actually fully parse the full block though?
        #  (similar thing applies to to_obj when publishing the block).
        #  (No need to SSZ (de)serialize all of it)
        #  Another idea - add the param local_blinded / blinded_local
        #  to the request, that way all returned blocks are blinded
        #  and much smaller! See https://github.com/ChainSafe/lodestar/issues/6219
        #  (probably not all CLs support this but still...)
        #  That would help a bit since we wouldn't be deserializing
        #  the execution payload - transactions.
        decode_function = (
            "decode_bytes" if isinstance(response.data, bytes) else "from_obj"
        )

        block_map = {
            SchemaBeaconAPI.ForkVersion.ELECTRA: (
                SpecBeaconBlock.ElectraBlindedBlock
                if response.execution_payload_blinded
                else SpecBeaconBlock.ElectraBlockContents
            ),
            # Block containers unchanged in Fulu => reusing Electra containers
            SchemaBeaconAPI.ForkVersion.FULU: (
                SpecBeaconBlock.ElectraBlindedBlock
                if response.execution_payload_blinded
                else SpecBeaconBlock.ElectraBlockContents
            ),
        }

        try:
            block_cls = block_map[response.version]
            return getattr(block_cls, decode_function)(response.data)
        except KeyError:
            raise ValueError(
                f"Unsupported block version {response.version} in response {response}"
            ) from None

    async def _produce_best_block(
        self,
        slot: int,
        graffiti: bytes,
        builder_boost_factor: int,
        randao_reveal: str,
        soft_timeout: float,
    ) -> SchemaBeaconAPI.ProduceBlockV3Response:
        """Gets the produce block response from all beacon nodes and returns the
        best one by its reported value.

        Most of the logic in here makes sure we don't wait too long for a block to be
        produced by an unresponsive beacon node.

        If no block has been returned within the soft timeout, we wait indefinitely
        for the first block to be returned by any beacon node and use that.
        """

        beacon_nodes_to_use = self.initialized_beacon_nodes
        if self.beacon_nodes_proposal:
            self.logger.info(
                f"Overriding beacon nodes for block proposal, using {[bn.host for bn in self.beacon_nodes_proposal]}",
            )
            beacon_nodes_to_use = self.beacon_nodes_proposal

        tasks = {
            asyncio.create_task(
                bn.produce_block_v3(
                    slot=slot,
                    graffiti=graffiti,
                    builder_boost_factor=builder_boost_factor,
                    randao_reveal=randao_reveal,
                ),
            )
            for bn in beacon_nodes_to_use
        }
        pending = tasks

        best_block_value = -1
        best_block_response = None
        start_time = asyncio.get_running_loop().time()
        remaining_soft_timeout = soft_timeout

        # Only compare consensus block value on Gnosis Chain / Chiado
        # since the execution payload value is in a different
        # currency (xDAI) and not easily comparable
        _compare_consensus_block_value_only = self.cli_args.network in [
            Network.GNOSIS,
            Network.CHIADO,
        ]

        while pending and remaining_soft_timeout > 0:
            done, pending = await asyncio.wait(
                pending,
                timeout=remaining_soft_timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for coro in done:
                try:
                    response = await coro
                except Exception as e:
                    self.logger.warning(
                        f"Failed to get a response from beacon node: {e!r}"
                    )
                    continue

                if _compare_consensus_block_value_only:
                    block_value = int(response.consensus_block_value)
                else:
                    block_value = int(response.consensus_block_value) + int(
                        response.execution_payload_value
                    )

                if block_value > best_block_value:
                    best_block_value = block_value
                    best_block_response = response

            # Calculate remaining timeout
            elapsed_time = asyncio.get_running_loop().time() - start_time
            remaining_soft_timeout = max(soft_timeout - elapsed_time, 0)

        if remaining_soft_timeout <= 0:
            self.logger.warning("Block production timeout reached.")

        # If no block has been returned yet, wait for the first one and return it
        # immediately.
        if best_block_response is None and pending:
            self.logger.warning(
                "No blocks received yet but tasks are pending - waiting"
                " for first block",
            )

            for coro_first in asyncio.as_completed(pending):
                try:
                    best_block_response = await coro_first
                    best_block_value = int(
                        best_block_response.consensus_block_value
                    ) + int(best_block_response.execution_payload_value)
                    # Exit loop
                    break
                except Exception as e:
                    self.logger.warning(
                        f"Failed to get a response from beacon node: {e!r}"
                    )
                    continue

        # Cancel pending requests
        for task in pending:
            task.cancel()

        if best_block_response is None:
            # We have exhausted all tasks and have not received a block response
            raise RuntimeError("Failed to get a response from all beacon nodes")

        self.logger.info(f"Proceeding with best block by value: {best_block_value}")
        return best_block_response

    async def produce_block_v3(
        self,
        slot: int,
        graffiti: bytes,
        builder_boost_factor: int,
        randao_reveal: str,
        soft_timeout: float,
    ) -> tuple[Container, SchemaBeaconAPI.ProduceBlockV3Response]:
        # TODO small room for improvement here.
        #  We are currently choosing the best block based on total
        #  block value (consensus+exec).
        #  We could however take the best beacon block
        #  and combine it with the best execution payload.
        #  That would take up some extra processing time though.
        best_block_response = await self._produce_best_block(
            slot=slot,
            graffiti=graffiti,
            builder_boost_factor=builder_boost_factor,
            randao_reveal=randao_reveal,
            soft_timeout=soft_timeout,
        )

        # Parse block
        return self._parse_block_response(
            response=best_block_response,
        ), best_block_response

    async def publish_block_v2(self, **kwargs: Any) -> None:
        if self.beacon_nodes_proposal:
            kwargs["beacon_nodes"] = self.beacon_nodes_proposal

        await self._get_all_beacon_node_responses(
            func_name="publish_block_v2",
            **kwargs,
        )

    async def publish_blinded_block_v2(self, **kwargs: Any) -> None:
        if self.beacon_nodes_proposal:
            kwargs["beacon_nodes"] = self.beacon_nodes_proposal

        await self._get_all_beacon_node_responses(
            func_name="publish_blinded_block_v2",
            **kwargs,
        )

    async def get_attester_duties(
        self,
        **kwargs: Any,
    ) -> SchemaBeaconAPI.GetAttesterDutiesResponse:
        return await self.best_beacon_node.get_attester_duties(**kwargs)

    async def prepare_beacon_committee_subscriptions(self, **kwargs: Any) -> None:
        await self._get_all_beacon_node_responses(
            func_name="prepare_beacon_committee_subscriptions",
            **kwargs,
        )

    async def produce_attestation_data_without_head_event(
        self,
        slot: int,
    ) -> SchemaBeaconAPI.AttestationData:
        # Maps beacon node hosts to their last returned AttestationData
        host_to_att_data: dict[str, SchemaBeaconAPI.AttestationData] = dict()
        att_data_counter: Counter[SchemaBeaconAPI.AttestationData] = Counter()

        while True:
            _round_start = asyncio.get_running_loop().time()

            tasks = [
                asyncio.create_task(
                    bn.produce_attestation_data(
                        slot=slot,
                    ),
                )
                for bn in self.initialized_beacon_nodes
            ]

            for coro in asyncio.as_completed(tasks):
                try:
                    host, att_data = await coro
                except Exception as e:
                    # We can tolerate some attestation data production failures
                    self.logger.warning(
                        f"Failed to produce attestation data: {e!r}",
                    )
                    continue

                prev_att_data = host_to_att_data.get(host)

                if att_data == prev_att_data:
                    # This host has already returned the same AttestationData in the past,
                    # no need to process it
                    continue

                # New AttestationData has arrived from this host
                self.logger.debug(f"AttestationData received from {host}: {att_data}")
                host_to_att_data[host] = att_data
                att_data_counter[att_data] += 1
                if prev_att_data is not None:
                    att_data_counter[prev_att_data] -= 1

                # Check if we reached the threshold for consensus
                if att_data_counter[att_data] >= self._attestation_consensus_threshold:
                    # Cancel pending tasks
                    for task in tasks:
                        task.cancel()

                    contributing_hosts = [
                        h for h, ad in host_to_att_data.items() if ad == att_data
                    ]

                    self.logger.debug(
                        f"Produced AttestationData without head event using {contributing_hosts}"
                    )

                    return att_data

            # If no consensus has been reached in this round,
            # rate-limit so we don't spam requests too quickly.
            # We wait at least 30ms from the start of this round.
            await asyncio.sleep(
                max(0.03 - (asyncio.get_running_loop().time() - _round_start), 0),
            )

    async def wait_for_attestation_data(
        self,
        expected_head_block_root: str,
        slot: int,
    ) -> SchemaBeaconAPI.AttestationData:
        tasks = [
            asyncio.create_task(
                bn.wait_for_attestation_data(
                    expected_head_block_root=expected_head_block_root,
                    slot=slot,
                )
            )
            for bn in self.initialized_beacon_nodes
        ]

        try:
            for coro in asyncio.as_completed(tasks):
                att_data = await coro
                for task in tasks:
                    task.cancel()
                return att_data
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            raise

        raise RuntimeError(
            f"Failed waiting for attestation data with block root {expected_head_block_root}"
        )

    async def wait_for_checkpoints(
        self,
        slot: int,
        expected_source_cp: SchemaBeaconAPI.Checkpoint,
        expected_target_cp: SchemaBeaconAPI.Checkpoint,
    ) -> None:
        tasks = [
            asyncio.create_task(
                bn.wait_for_checkpoints(
                    slot=slot,
                    expected_source_cp=expected_source_cp,
                    expected_target_cp=expected_target_cp,
                )
            )
            for bn in self.initialized_beacon_nodes
        ]

        try:
            for total_confirmations, coro in enumerate(
                asyncio.as_completed(tasks), start=1
            ):
                await coro
                if total_confirmations >= self._attestation_consensus_threshold:
                    for task in tasks:
                        task.cancel()
                    return
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            raise

    async def publish_attestations(
        self,
        attestations: list[SchemaBeaconAPI.SingleAttestation],
        fork_version: SchemaBeaconAPI.ForkVersion,
    ) -> None:
        await self._get_all_beacon_node_responses(
            func_name="publish_attestations",
            attestations=attestations,
            fork_version=fork_version,
        )

    async def get_aggregate_attestation_v2(
        self,
        attestation_data_root: str,
        slot: int,
        committee_index: int,
    ) -> "SpecAttestation.AttestationElectra":
        aggregates: list[
            SpecAttestation.AttestationElectra
        ] = await self._get_all_beacon_node_responses(
            func_name="get_aggregate_attestation_v2",
            attestation_data_root=attestation_data_root,
            slot=slot,
            committee_index=committee_index,
        )

        best_aggregate = None
        best_aggregate_attester_count = 0

        for aggregate in aggregates:
            attester_count = sum(aggregate.aggregation_bits)

            if attester_count > best_aggregate_attester_count:
                best_aggregate = aggregate
                best_aggregate_attester_count = attester_count

                # Return early if the aggregate is ideal
                if best_aggregate_attester_count == len(aggregate.aggregation_bits):
                    return aggregate

        if best_aggregate is None:
            raise RuntimeError("best_aggregate is None")

        return best_aggregate

    async def get_aggregate_attestations_v2(
        self,
        attestation_data_root: str,
        slot: int,
        committee_indices: set[int],
    ) -> AsyncIterator["SpecAttestation.AttestationElectra"]:
        tasks = [
            self.get_aggregate_attestation_v2(
                attestation_data_root=attestation_data_root,
                slot=slot,
                committee_index=committee_index,
            )
            for committee_index in committee_indices
        ]

        for task in asyncio.as_completed(tasks):
            try:
                yield await task
            except Exception as e:
                self.metrics.errors_c.labels(
                    error_type=ErrorType.AGGREGATE_ATTESTATION_PRODUCE.value,
                ).inc()
                self.logger.exception(
                    f"Failed to produce aggregate attestation for slot {slot}, root {attestation_data_root}: {e!r}",
                )

    async def publish_aggregate_and_proofs(
        self,
        signed_aggregate_and_proofs: list[tuple[dict, str]],  # type: ignore[type-arg]
        fork_version: SchemaBeaconAPI.ForkVersion,
    ) -> None:
        await self._get_all_beacon_node_responses(
            func_name="publish_aggregate_and_proofs",
            signed_aggregate_and_proofs=signed_aggregate_and_proofs,
            fork_version=fork_version,
        )

    async def get_sync_duties(
        self,
        **kwargs: Any,
    ) -> SchemaBeaconAPI.GetSyncDutiesResponse:
        return await self.best_beacon_node.get_sync_duties(**kwargs)

    async def prepare_sync_committee_subscriptions(self, **kwargs: Any) -> None:
        await self._get_all_beacon_node_responses(
            func_name="prepare_sync_committee_subscriptions",
            **kwargs,
        )

    async def get_block_root(self, block_id: str) -> str:
        return await self.best_beacon_node.get_block_root(block_id=block_id)

    async def publish_sync_committee_messages(self, **kwargs: Any) -> None:
        await self._get_all_beacon_node_responses(
            func_name="publish_sync_committee_messages",
            **kwargs,
        )

    async def get_sync_committee_contribution(
        self,
        slot: int,
        subcommittee_index: int,
        beacon_block_root: str,
    ) -> "SpecSyncCommittee.Contribution":
        contributions: list[
            SpecSyncCommittee.Contribution
        ] = await self._get_all_beacon_node_responses(
            func_name="get_sync_committee_contribution",
            slot=slot,
            subcommittee_index=subcommittee_index,
            beacon_block_root=beacon_block_root,
        )

        best_contribution = None
        best_contribution_participant_count = 0

        for contribution in contributions:
            participant_count = sum(contribution.aggregation_bits)

            if participant_count > best_contribution_participant_count:
                best_contribution = contribution
                best_contribution_participant_count = participant_count

                # Return early if the contribution is ideal
                if best_contribution_participant_count == len(
                    contribution.aggregation_bits,
                ):
                    return contribution

        if best_contribution is None:
            raise RuntimeError("best_contribution is None")

        return best_contribution

    async def get_sync_committee_contributions(
        self,
        slot: int,
        subcommittee_indices: set[int],
        beacon_block_root: str,
    ) -> AsyncIterator[Container]:
        tasks = [
            self.get_sync_committee_contribution(
                slot=slot,
                subcommittee_index=subcommittee_index,
                beacon_block_root=beacon_block_root,
            )
            for subcommittee_index in subcommittee_indices
        ]

        for task in asyncio.as_completed(tasks):
            try:
                yield await task
            except Exception:
                self.metrics.errors_c.labels(
                    error_type=ErrorType.SYNC_COMMITTEE_CONTRIBUTION_PRODUCE.value,
                ).inc()

    async def publish_sync_committee_contribution_and_proofs(
        self,
        signed_contribution_and_proofs: list[tuple[dict, str]],  # type: ignore[type-arg]
    ) -> None:
        await self._get_all_beacon_node_responses(
            func_name="publish_sync_committee_contribution_and_proofs",
            signed_contribution_and_proofs=signed_contribution_and_proofs,
        )
