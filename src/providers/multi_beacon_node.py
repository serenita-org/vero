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
import datetime
import logging
from collections import Counter
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from opentelemetry import trace
from remerkleable.complex import Container

from args import CLIArgs
from observability import ErrorType, get_shared_metrics
from providers.beacon_node import BeaconNode
from schemas import SchemaBeaconAPI, SchemaValidator
from spec.attestation import Attestation, AttestationData
from spec.block import BeaconBlockClass
from spec.sync_committee import SyncCommitteeContributionClass

(_ERRORS_METRIC,) = get_shared_metrics()


class AttestationConsensusFailure(Exception):
    pass


class MultiBeaconNode:
    def __init__(
        self,
        beacon_node_urls: list[str],
        beacon_node_urls_proposal: list[str],
        scheduler: AsyncIOScheduler,
        cli_args: CLIArgs,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.getLogger().level)

        self.tracer = trace.get_tracer(self.__class__.__name__)

        self.beacon_nodes = [
            BeaconNode(base_url=base_url, scheduler=scheduler)
            for base_url in beacon_node_urls
        ]
        self.beacon_nodes_proposal = [
            BeaconNode(base_url=base_url, scheduler=scheduler)
            for base_url in beacon_node_urls_proposal
        ]

        self._attestation_consensus_threshold = cli_args.attestation_consensus_threshold

    async def initialize(self) -> None:
        # Attempt to fully initialize the connected beacon nodes
        await asyncio.gather(*(bn.initialize_full() for bn in self.beacon_nodes))

        successfully_initialized = len([b for b in self.beacon_nodes if b.initialized])
        if successfully_initialized < self._attestation_consensus_threshold:
            raise RuntimeError(
                f"Failed to fully initialize a sufficient amount of beacon nodes -"
                f" {successfully_initialized}/{len(self.beacon_nodes)} initialized",
            )

        # Check the connected beacon nodes genesis, spec
        if (
            not len({bn.genesis for bn in self.beacon_nodes if bn.initialized})
            # not len(set([bn.genesis for bn in self.beacon_nodes if bn.initialized]))
            == 1
        ):
            raise RuntimeError(
                f"Beacon nodes provided different genesis:"
                f" {[bn.genesis for bn in self.beacon_nodes if bn.initialized]}",
            )
        if not len({bn.spec for bn in self.beacon_nodes if bn.initialized}) == 1:
            raise RuntimeError(
                f"Beacon nodes provided different specs:"
                f" {[bn.spec for bn in self.beacon_nodes if bn.initialized]}",
            )

        self.logger.info(
            f"Successfully initialized"
            f" {successfully_initialized}"
            f"/{len(self.beacon_nodes)}"
            f" beacon nodes",
        )

        # Dynamically create some of the SSZ classes
        spec = next(bn.spec for bn in self.beacon_nodes if bn.initialized)
        BeaconBlockClass.initialize(spec=spec)
        SyncCommitteeContributionClass.initialize(spec=spec)

    async def __aenter__(self) -> "MultiBeaconNode":
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
            for bn in sorted(self.beacon_nodes, key=lambda bn: bn.score, reverse=True)
            if bn.initialized
        )

    async def _get_first_beacon_node_response(
        self,
        func_name: str,
        **kwargs: Any,
    ) -> Any:
        tasks = [
            asyncio.create_task(getattr(bn, func_name)(**kwargs))
            for bn in self.beacon_nodes
            if bn.initialized
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
        beacon_nodes_to_use = beacon_nodes or [
            bn for bn in self.beacon_nodes if bn.initialized
        ]

        responses: list[Any] = []
        for res in await asyncio.gather(
            *[getattr(bn, func_name)(**kwargs) for bn in beacon_nodes_to_use],
            return_exceptions=True,
        ):
            if isinstance(res, Exception):
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
    ) -> Container:
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
        if response.version == SchemaBeaconAPI.BeaconBlockVersion.DENEB:
            if response.execution_payload_blinded:
                return BeaconBlockClass.DenebBlinded.from_obj(response.data)
            return BeaconBlockClass.Deneb.from_obj(response.data["block"])
        raise ValueError(
            f"Unsupported block version {response.version} in response {response}",
        )

    async def _produce_best_block(
        self,
        slot: int,
        graffiti: bytes,
        builder_boost_factor: int,
        randao_reveal: str,
    ) -> SchemaBeaconAPI.ProduceBlockV3Response:
        """Gets the produce block response from all beacon nodes and returns the
        best one by its reported value.

        Most of the logic in here makes sure we don't wait too long for a block to be
        produced by an unresponsive beacon node.
        """
        spec = next(bn.spec for bn in self.beacon_nodes if bn.initialized)

        # Times out at 1/3 of the SECONDS_PER_SLOT spec value into the slot
        # (e.g. 1.33s for Ethereum, 0.55s for Gnosis Chain).
        # If no block has been returned by that point, it waits indefinitely for the
        # first block to be returned by any beacon node.
        timeout = (1 / 3) * (int(spec.SECONDS_PER_SLOT) / int(spec.INTERVALS_PER_SLOT))

        beacon_nodes_to_use = [bn for bn in self.beacon_nodes if bn.initialized]
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

        best_block_value = 0
        best_block_response = None
        start_time = asyncio.get_running_loop().time()
        remaining_timeout = timeout

        while pending and remaining_timeout > 0:
            done, pending = await asyncio.wait(
                pending,
                timeout=remaining_timeout,
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

                block_value = int(response.consensus_block_value) + int(
                    response.execution_payload_value
                )

                if block_value > best_block_value:
                    best_block_value = block_value
                    best_block_response = response

            # Calculate remaining timeout
            elapsed_time = asyncio.get_running_loop().time() - start_time
            remaining_timeout = max(timeout - elapsed_time, 0)

        if remaining_timeout <= 0:
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

    async def _produce_attestation_data_from_head_event(
        self,
        slot: int,
        committee_index: int,
        deadline: datetime.datetime,
        head_event: SchemaBeaconAPI.HeadEvent,
    ) -> AttestationData:
        tasks = [
            asyncio.create_task(
                bn.wait_for_attestation_data(
                    expected_head_block_root=head_event.block,
                    slot=slot,
                    committee_index=committee_index,
                ),
            )
            for bn in self.beacon_nodes
            if bn.initialized
        ]
        head_match_count = 0
        for coro in asyncio.as_completed(
            tasks,
            timeout=(deadline - datetime.datetime.now(tz=pytz.UTC)).total_seconds(),
        ):
            try:
                att_data = await coro
                head_match_count += 1
                if head_match_count >= self._attestation_consensus_threshold:
                    # Cancel pending tasks
                    for task in tasks:
                        task.cancel()
                    return att_data
            except TimeoutError:
                # Deadline reached
                continue
            except Exception as e:
                self.logger.error(
                    f"Failed waiting for attestation data: {e!r}",
                    exc_info=self.logger.isEnabledFor(logging.DEBUG),
                )
                continue

        # Cancel pending tasks
        for task in tasks:
            task.cancel()
        raise AttestationConsensusFailure(
            f"Failed to reach consensus on attestation data for slot {slot} among connected beacon nodes. Expected head block root: {head_event.block}",
        )

    async def _produce_attestation_data_without_head_event(
        self,
        slot: int,
        committee_index: int,
        deadline: datetime.datetime,
    ) -> AttestationData:
        while datetime.datetime.now(pytz.UTC) < deadline:
            _round_start = asyncio.get_running_loop().time()
            head_block_root_counter: Counter[str] = Counter()

            tasks = [
                asyncio.create_task(
                    bn.produce_attestation_data(
                        slot=slot,
                        committee_index=committee_index,
                    ),
                )
                for bn in self.beacon_nodes
                if bn.initialized
            ]

            for coro in asyncio.as_completed(tasks):
                try:
                    att_data = await coro
                except Exception as e:
                    self.logger.error(
                        f"Failed to produce attestation data: {e!r}",
                        exc_info=self.logger.isEnabledFor(logging.DEBUG),
                    )
                    continue

                block_root = att_data.beacon_block_root.to_obj()
                head_block_root_counter[block_root] += 1
                if (
                    head_block_root_counter[block_root]
                    >= self._attestation_consensus_threshold
                ):
                    # Cancel pending tasks
                    for task in tasks:
                        task.cancel()
                    return att_data

            # Rate-limiting - wait at least 30ms in between requests
            await asyncio.sleep(
                max(0.03 - (asyncio.get_running_loop().time() - _round_start), 0),
            )
        raise AttestationConsensusFailure(
            f"Failed to reach consensus on attestation data for slot {slot} among connected beacon nodes.",
        )

    async def _produce_attestation_data(
        self,
        slot: int,
        committee_index: int,
        deadline: datetime.datetime,
        head_event: SchemaBeaconAPI.HeadEvent | None,
    ) -> AttestationData:
        # Slightly different algorithms depending on whether
        # a head event has been emitted.
        # A) A head event was emitted
        #    We wait for enough beacon nodes to report the same
        #    head block root as is present in the head event.
        # B) No head event was emitted
        #    We wait for enough beacon nodes to report the same
        #    head block root.
        if head_event:
            return await self._produce_attestation_data_from_head_event(
                slot=slot,
                committee_index=committee_index,
                deadline=deadline,
                head_event=head_event,
            )
        return await self._produce_attestation_data_without_head_event(
            slot=slot,
            committee_index=committee_index,
            deadline=deadline,
        )

    async def produce_attestation_data(
        self,
        slot: int,
        committee_index: int,
        deadline: datetime.datetime,
        head_event: SchemaBeaconAPI.HeadEvent | None = None,
    ) -> AttestationData:
        """Returns attestation data from the connected beacon nodes.

        If a head event is provided, the function will wait until enough beacon nodes
        has processed the same head block.

        Some example situations that can occur and how they are handled:
        - 2s into the slot, we receive a head event from one beacon node,
          but the rest of connected beacon nodes hasn't processed that block yet
          --> we wait for enough beacon nodes to report the same head block
              (even if that means submitting the attestation later than 4s into the slot)
        - 4s into the slot, we haven't received a head event.
          --> We request all beacon nodes to produce attestation data and wait until enough
              beacon nodes agrees on a head block. Then we attest to that.
        """
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.produce_attestation_data",
            attributes={
                "head_event.beacon_block_root": head_event.block
                if head_event
                else str(None),
            },
        ):
            return await self._produce_attestation_data(
                slot=slot,
                committee_index=committee_index,
                deadline=deadline,
                head_event=head_event,
            )

    async def publish_attestations(self, **kwargs: Any) -> None:
        await self._get_all_beacon_node_responses(
            func_name="publish_attestations",
            **kwargs,
        )

    async def get_aggregate_attestation(
        self,
        attestation_data: AttestationData,
        committee_index: int,
    ) -> Attestation:
        _att_data = attestation_data.copy()
        _att_data.index = committee_index

        aggregates: list[Attestation] = await self._get_all_beacon_node_responses(
            func_name="get_aggregate_attestation",
            attestation_data=_att_data,
        )

        best_aggregate = None
        best_aggregate_attester_count = 0

        for aggregate in aggregates:
            if sum(aggregate.aggregation_bits) > best_aggregate_attester_count:
                best_aggregate = aggregate
                best_aggregate_attester_count = sum(aggregate.aggregation_bits)

                # Return early if all attesters' votes are included in the aggregate
                if best_aggregate_attester_count == len(aggregate.aggregation_bits):
                    return aggregate

        if best_aggregate is None:
            raise RuntimeError("best_aggregate is None")

        return best_aggregate

    async def get_aggregate_attestations(
        self,
        attestation_data: AttestationData,
        committee_indices: set[int],
    ) -> AsyncIterator[AttestationData]:
        tasks = [
            self.get_aggregate_attestation(
                attestation_data=attestation_data,
                committee_index=committee_index,
            )
            for committee_index in committee_indices
        ]

        for task in asyncio.as_completed(tasks):
            try:
                yield await task
            except Exception:
                _ERRORS_METRIC.labels(
                    error_type=ErrorType.AGGREGATE_ATTESTATION_PRODUCE.value,
                ).inc()

    async def publish_aggregate_and_proofs(
        self,
        signed_aggregate_and_proofs: list[tuple[dict, str]],  # type: ignore[type-arg]
    ) -> None:
        await self._get_all_beacon_node_responses(
            func_name="publish_aggregate_and_proofs",
            signed_aggregate_and_proofs=signed_aggregate_and_proofs,
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
    ) -> Container:
        contributions: list[Container] = await self._get_all_beacon_node_responses(
            func_name="get_sync_committee_contribution",
            slot=slot,
            subcommittee_index=subcommittee_index,
            beacon_block_root=beacon_block_root,
        )

        best_contribution = None
        best_contribution_participant_count = 0

        for contribution in contributions:
            if sum(contribution.aggregation_bits) > best_contribution_participant_count:
                best_contribution = contribution
                best_contribution_participant_count = sum(contribution.aggregation_bits)

                # Return early if all attesters' votes are included in the aggregate
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
                _ERRORS_METRIC.labels(
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
