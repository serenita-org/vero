"""These test the additional behavior of MultiBeaconNode (vs the simple BeaconNode)
when multiple beacon nodes are provided to it. That includes:
- initialization
- requesting attestation aggregates from all beacon nodes and returning the best one
- requesting sync committee contributions from all beacon nodes and returning the best one
"""

import contextlib
import os
import re
from copy import deepcopy
from functools import partial

import pytest
from aiohttp.web_exceptions import HTTPRequestTimeout
from aioresponses import CallbackResult, aioresponses
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from remerkleable.bitfields import Bitlist, Bitvector

from args import CLIArgs, _process_attestation_consensus_threshold
from providers import BeaconChain, MultiBeaconNode
from schemas import SchemaBeaconAPI
from spec.attestation import AttestationData, SpecAttestation
from spec.base import SpecFulu
from spec.constants import SYNC_COMMITTEE_SUBNET_COUNT
from spec.sync_committee import SpecSyncCommittee
from tasks import TaskManager


@pytest.mark.parametrize(
    argnames=(
        "beacon_node_urls",
        "beacon_node_availabilities",
        "expected_initialization_success",
    ),
    argvalues=[
        pytest.param(
            [
                "http://beacon-node-a:1234",
            ],
            [
                True,
            ],
            True,
            id="1/1 available beacon nodes",
        ),
        pytest.param(
            [
                "http://beacon-node-a:1234",
                "http://beacon-node-b:1234",
                "http://beacon-node-c:1234",
            ],
            [True, False, True],
            True,
            id="2/3 available beacon nodes",
        ),
        pytest.param(
            [
                "http://beacon-node-a:1234",
                "http://beacon-node-b:1234",
                "http://beacon-node-c:1234",
            ],
            [True, False, False],
            False,
            id="1/3 available beacon nodes -> init fails",
        ),
    ],
)
async def test_initialize(
    beacon_node_urls: list[str],
    beacon_node_availabilities: list[bool],
    expected_initialization_success: bool,
    mocked_fork_response: dict,  # type: ignore[type-arg]
    mocked_genesis_response: dict,  # type: ignore[type-arg]
    beacon_chain: BeaconChain,
    spec: SpecFulu,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
    cli_args: CLIArgs,
) -> None:
    """Tests that the multi-beacon node is able to initialize if enough
    of its supplied beacon nodes are available.
    """
    assert len(beacon_node_urls) == len(beacon_node_availabilities)
    _cli_args_for_test = deepcopy(cli_args)
    _cli_args_for_test.attestation_consensus_threshold = (
        _process_attestation_consensus_threshold(None, beacon_node_urls)
    )

    async with contextlib.AsyncExitStack() as exit_stack:
        m = exit_stack.enter_context(aioresponses())

        for _url, beacon_node_available in zip(
            beacon_node_urls,
            beacon_node_availabilities,
            strict=True,
        ):
            if beacon_node_available:
                m.get(
                    url=re.compile(
                        r"http://beacon-node-\w:1234/eth/v1/beacon/states/head/fork",
                    ),
                    callback=lambda *args, **kwargs: CallbackResult(
                        payload=mocked_fork_response,
                    ),
                )
                m.get(
                    url=re.compile(r"http://beacon-node-\w:1234/eth/v1/beacon/genesis"),
                    callback=lambda *args, **kwargs: CallbackResult(
                        payload=mocked_genesis_response,
                    ),
                )
                m.get(
                    url=re.compile(r"http://beacon-node-\w:1234/eth/v1/config/spec"),
                    callback=lambda *args, **kwargs: CallbackResult(
                        payload=dict(data=spec.to_obj()),
                    ),
                )
                m.get(
                    url=re.compile(r"http://beacon-node-\w:1234/eth/v1/node/version"),
                    callback=lambda *args, **kwargs: CallbackResult(
                        payload=dict(data=dict(version="vero/test")),
                    ),
                )
            else:
                # Fail the first request that is made during initialization
                m.get(
                    url=re.compile(
                        r"http://beacon-node-\w:1234/eth/v1/beacon/states/head/fork",
                    ),
                    exception=ValueError("Beacon node unavailable"),
                )

        mbn_base = MultiBeaconNode(
            beacon_node_urls=beacon_node_urls,
            beacon_node_urls_proposal=[],
            spec=spec,
            scheduler=scheduler,
            task_manager=task_manager,
            cli_args=_cli_args_for_test,
        )
        if expected_initialization_success:
            await exit_stack.enter_async_context(mbn_base)
        else:
            with pytest.raises(
                RuntimeError,
                match="Failed to fully initialize a sufficient amount of beacon nodes",
            ):
                await exit_stack.enter_async_context(mbn_base)


@pytest.mark.parametrize(
    argnames=("numbers_of_attesting_indices", "best_aggregate_score"),
    argvalues=[
        pytest.param(
            [4, 5, 3],
            5,  # Best aggregate has 5 attesting indices
            id="Happy path - aggregates returned from all beacon nodes",
        ),
        pytest.param(
            [HTTPRequestTimeout(), 5, 3],
            5,  # Best aggregate has 5 attesting indices
            id="2/3 aggregates returned, 1 request timeout",
        ),
        pytest.param(
            [
                HTTPRequestTimeout(),
                HTTPRequestTimeout(),
                4,
            ],
            4,  # Best aggregate has 4 attesting indices
            id="1/3 aggregates returned, 2 requests time out",
        ),
        pytest.param(
            [
                HTTPRequestTimeout(),
                HTTPRequestTimeout(),
                HTTPRequestTimeout(),
            ],
            None,
            id="No aggregates returned -> method raises an Exception",
        ),
    ],
)
async def test_get_aggregate_attestation(
    numbers_of_attesting_indices: list[Exception | int],
    best_aggregate_score: int,
    beacon_chain: BeaconChain,
    multi_beacon_node_three_inited_nodes: MultiBeaconNode,
) -> None:
    """Tests that the multi-beacon requests aggregate attestations from all beacon nodes
    and returns the one with the highest value.
    """
    with aioresponses() as m:
        for number_of_attesting_indices in numbers_of_attesting_indices:
            if isinstance(number_of_attesting_indices, int):
                bitlist_length = (
                    beacon_chain.MAX_VALIDATORS_PER_COMMITTEE
                    * beacon_chain.MAX_COMMITTEES_PER_SLOT
                )
                agg_bits_to_return = Bitlist[bitlist_length](False for _ in range(10))
                for idx in range(number_of_attesting_indices):
                    agg_bits_to_return[idx] = True
                _callback = partial(
                    lambda _bits, *args, **kwargs: CallbackResult(
                        payload=dict(
                            version=SchemaBeaconAPI.ForkVersion.FULU.value,
                            data=SpecAttestation.AttestationElectra(
                                aggregation_bits=_bits,
                            ).to_obj(),
                        ),
                    ),
                    agg_bits_to_return,
                )
                m.get(
                    url=re.compile(
                        r"http://beacon-node-\w:1234/eth/v2/validator/aggregate_attestation",
                    ),
                    callback=_callback,
                )
            elif isinstance(number_of_attesting_indices, Exception):
                m.get(
                    url=re.compile(
                        r"http://beacon-node-\w:1234/eth/v2/validator/aggregate_attestation",
                    ),
                    exception=number_of_attesting_indices,
                )
            else:
                raise NotImplementedError

        if all(isinstance(n, Exception) for n in numbers_of_attesting_indices):
            with pytest.raises(
                RuntimeError,
                match="Failed to get a response from all beacon nodes",
            ):
                _ = await multi_beacon_node_three_inited_nodes.get_aggregate_attestation_v2(
                    attestation_data_root="0x"
                    + AttestationData().hash_tree_root().hex(),
                    slot=beacon_chain.current_slot,
                    committee_index=3,
                )
        else:
            returned_aggregate = (
                await multi_beacon_node_three_inited_nodes.get_aggregate_attestation_v2(
                    attestation_data_root="0x"
                    + AttestationData().hash_tree_root().hex(),
                    slot=beacon_chain.current_slot,
                    committee_index=3,
                )
            )
            assert sum(returned_aggregate.aggregation_bits) == best_aggregate_score


@pytest.mark.parametrize(
    argnames=("numbers_of_root_matching_indices", "best_contribution_score"),
    argvalues=[
        pytest.param(
            [4, 5, 3],
            5,  # Best contribution has 5 block-root-matching indices
            id="Happy path - aggregates returned from all beacon nodes",
        ),
        pytest.param(
            [
                HTTPRequestTimeout(),
                5,
                3,
            ],
            5,  # Best contribution has 5 block-root-matching indices
            id="2/3 aggregates returned, 1 request timeout",
        ),
        pytest.param(
            [HTTPRequestTimeout(), HTTPRequestTimeout(), 4],
            4,  # Best contribution has 4 block-root-matching indices
            id="1/3 aggregates returned, 2 requests time out",
        ),
        pytest.param(
            [
                HTTPRequestTimeout(),
                HTTPRequestTimeout(),
                HTTPRequestTimeout(),
            ],
            None,
            id="No aggregates returned -> method raises an Exception",
        ),
    ],
)
async def test_get_sync_committee_contribution(
    numbers_of_root_matching_indices: list[Exception | int],
    best_contribution_score: int,
    multi_beacon_node_three_inited_nodes: MultiBeaconNode,
    spec: SpecFulu,
) -> None:
    """Tests that the multi-beacon requests sync committee contributions from all beacon nodes
    and returns the one with the highest value.
    """
    with aioresponses() as m:
        for number_of_root_matching_indices in numbers_of_root_matching_indices:
            if isinstance(number_of_root_matching_indices, int):
                bitlist_size = spec.SYNC_COMMITTEE_SIZE // SYNC_COMMITTEE_SUBNET_COUNT
                agg_bits_to_return = Bitvector[bitlist_size](
                    False for _ in range(bitlist_size)
                )
                for idx in range(number_of_root_matching_indices):
                    agg_bits_to_return[idx] = True
                _callback = partial(
                    lambda _bits, *args, **kwargs: CallbackResult(
                        payload=dict(
                            data=SpecSyncCommittee.Contribution(
                                aggregation_bits=_bits,
                            ).to_obj(),
                        ),
                    ),
                    agg_bits_to_return,
                )
                m.get(
                    url=re.compile(
                        r"http://beacon-node-\w:1234/eth/v1/validator/sync_committee_contribution",
                    ),
                    callback=_callback,
                )
            elif isinstance(number_of_root_matching_indices, Exception):
                m.get(
                    url=re.compile(
                        r"http://beacon-node-\w:1234/eth/v1/validator/sync_committee_contribution",
                    ),
                    exception=number_of_root_matching_indices,
                )
            else:
                raise NotImplementedError

        if all(isinstance(n, Exception) for n in numbers_of_root_matching_indices):
            with pytest.raises(
                RuntimeError,
                match="Failed to get a response from all beacon nodes",
            ):
                _ = await multi_beacon_node_three_inited_nodes.get_sync_committee_contribution(
                    slot=123,
                    subcommittee_index=1,
                    beacon_block_root="0x" + os.urandom(32).hex(),
                )
        else:
            returned_contribution = await multi_beacon_node_three_inited_nodes.get_sync_committee_contribution(
                slot=123,
                subcommittee_index=1,
                beacon_block_root="0x" + os.urandom(32).hex(),
            )
            assert (
                sum(returned_contribution.aggregation_bits) == best_contribution_score
            )
