"""These test the additional behavior of MultiBeaconNode (vs the simple BeaconNode)
when multiple beacon nodes are provided to it. That includes:
- initialization
- requesting attestation aggregates from all beacon nodes and returning the best one
- requesting sync committee contributions from all beacon nodes and returning the best one
"""

import contextlib
import os
import re
from functools import partial

import pytest
from aiohttp.web_exceptions import HTTPRequestTimeout
from aioresponses import CallbackResult, aioresponses
from remerkleable.bitfields import Bitlist, Bitvector

from args import CLIArgs
from providers import BeaconChain, MultiBeaconNode, Vero
from schemas import SchemaBeaconAPI
from spec.attestation import AttestationData, SpecAttestation
from spec.base import SpecGloas
from spec.constants import SYNC_COMMITTEE_SUBNET_COUNT
from spec.sync_committee import SpecSyncCommittee


@pytest.mark.parametrize(
    argnames=(
        "cli_args",
        "beacon_node_availabilities",
        "expected_initialization_success",
    ),
    argvalues=[
        pytest.param(
            {
                "beacon_node_urls": ["http://beacon-node-a:1234"],
            },
            [True],
            True,
            id="1/1 available beacon nodes",
        ),
        pytest.param(
            {
                "beacon_node_urls": [
                    "http://beacon-node-a:1234",
                    "http://beacon-node-b:1234",
                    "http://beacon-node-c:1234",
                ],
            },
            [True, False, True],
            True,
            id="2/3 available beacon nodes",
        ),
        pytest.param(
            {
                "beacon_node_urls": [
                    "http://beacon-node-a:1234",
                    "http://beacon-node-b:1234",
                    "http://beacon-node-c:1234",
                ],
            },
            [True, False, False],
            False,
            id="1/3 available beacon nodes -> init fails",
        ),
    ],
    indirect=["cli_args"],
)
async def test_initialize(
    beacon_node_availabilities: list[bool],
    expected_initialization_success: bool,
    cli_args: CLIArgs,
    vero: Vero,
) -> None:
    """Tests that the multi-beacon node is able to initialize if enough
    of its supplied beacon nodes are available.
    """
    assert len(cli_args.beacon_node_urls) == len(beacon_node_availabilities)

    async with contextlib.AsyncExitStack() as exit_stack:
        m = exit_stack.enter_context(aioresponses())

        for bn_url, beacon_node_available in zip(
            cli_args.beacon_node_urls,
            beacon_node_availabilities,
            strict=True,
        ):
            if beacon_node_available:
                m.get(
                    url=re.compile(rf"{bn_url}/eth/v1/config/spec"),
                    callback=lambda *args, **kwargs: CallbackResult(
                        payload=dict(data=vero.spec.to_obj()),
                    ),
                )
                m.get(
                    url=re.compile(rf"{bn_url}/eth/v1/node/version"),
                    callback=lambda *args, **kwargs: CallbackResult(
                        payload=dict(data=dict(version="beacon-node/test")),
                    ),
                )
            else:
                # Fail the first request made during initialization
                m.get(
                    url=re.compile(rf"{bn_url}/eth/v1/config/spec"),
                    exception=ValueError("Beacon node unavailable"),
                )

        mbn_base = MultiBeaconNode(vero=vero)
        mbn_base._init_timeout = 1
        for bn in mbn_base.beacon_nodes:
            bn._init_retry_interval = 0.1

        if expected_initialization_success:
            await exit_stack.enter_async_context(mbn_base)
        else:
            with pytest.raises(
                RuntimeError,
                match="Failed to fully initialize a sufficient amount of beacon nodes",
            ):
                await exit_stack.enter_async_context(mbn_base)


@pytest.mark.parametrize(
    argnames="cli_args",
    argvalues=[
        pytest.param(
            {
                "beacon_node_urls": [
                    "http://beacon-node-a:1234",
                    "http://beacon-node-b:1234",
                    "http://beacon-node-c:1234",
                ],
                # Set the consensus threshold to 3/3, requiring all beacon nodes
                # to initialize successfully
                "attestation_consensus_threshold": 3,
            },
            id="1 bn offline at first, with 3/3 threshold",
        ),
    ],
    indirect=["cli_args"],
)
async def test_initialize_retry_logic(
    beacon_chain: BeaconChain,
    spec: SpecGloas,
    cli_args: CLIArgs,
    vero: Vero,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Tests that the multi-beacon node correctly handles retry logic during initialization.
    This logic was improved in response to a bug report (https://github.com/serenita-org/vero/issues/245)
    where Vero attempted to initialize already-initialized beacon nodes which resulted in
    ERROR-level messages in the logs.
    """
    async with contextlib.AsyncExitStack() as exit_stack:
        m = exit_stack.enter_context(aioresponses())

        # Mock responses.
        # Beacon node A and B are online right away and stay online.
        # Beacon node C is offline at first but becomes available later.
        # This means the very first initialization fails, and
        # the next one succeeds.
        online_bn_urls = vero.cli_args.beacon_node_urls[:2]
        initially_offline_bn_urls = vero.cli_args.beacon_node_urls[2:3]

        for _url in online_bn_urls:
            m.get(
                url=re.compile(rf"{_url}/eth/v1/config/spec"),
                callback=lambda *args, **kwargs: CallbackResult(
                    payload=dict(data=spec.to_obj()),
                ),
                repeat=True,
            )
            m.get(
                url=re.compile(rf"{_url}/eth/v1/node/version"),
                callback=lambda *args, **kwargs: CallbackResult(
                    payload=dict(data=dict(version="vero/test")),
                ),
                repeat=True,
            )

        for _url in initially_offline_bn_urls:
            # Fail the first request made during initialization, making the first init fail
            m.get(
                url=re.compile(rf"{_url}/eth/v1/config/spec"),
                exception=ValueError("Beacon node unavailable"),
            )

            # After the first init fails, the rest of the responses should return fine
            m.get(
                url=re.compile(rf"{_url}/eth/v1/config/spec"),
                callback=lambda *args, **kwargs: CallbackResult(
                    payload=dict(data=spec.to_obj()),
                ),
                repeat=True,
            )
            m.get(
                url=re.compile(rf"{_url}/eth/v1/node/version"),
                callback=lambda *args, **kwargs: CallbackResult(
                    payload=dict(data=dict(version="vero/test")),
                ),
                repeat=True,
            )
        mbn_base = MultiBeaconNode(vero=vero)
        mbn_base._init_timeout = 1
        for bn in mbn_base.beacon_nodes:
            bn._init_retry_interval = 0.1

        await exit_stack.enter_async_context(mbn_base)

        # First init of beacon-node-c will fail, causing the MultiBeaconNode
        # initialization to fail at first too.
        assert (
            "Failed to initialize beacon node at http://beacon-node-c:1234: ValueError('Beacon node unavailable'). Retrying in 0.1 seconds."
            in caplog.messages
        )
        assert (
            "Failed to fully initialize a sufficient amount of beacon nodes - 2/3 initialized (required: 3)"
            in caplog.messages
        )
        # The next requests to beacon-node-c succeed though, allowing it to initialize
        # successfully on the second attempt.
        assert "Initialized beacon node at http://beacon-node-c:1234" in caplog.messages
        # This then allows the MultiBeaconNode to initialize as well.
        assert "Successfully initialized 3/3 beacon nodes" in caplog.messages
        assert len(mbn_base.initialized_beacon_nodes) == 3

        # The above scenario should not result in multiple initialization attempts
        # for the BeaconNode instances (which cause ConflictingIdError exceptions
        # in the scheduler for the `update_node_version` job).
        assert not any("ConflictingIdError" in m for m in caplog.messages)


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
@pytest.mark.parametrize(
    argnames="cli_args",
    argvalues=[
        pytest.param(
            {
                "beacon_node_urls": [
                    "http://beacon-node-a:1234",
                    "http://beacon-node-b:1234",
                    "http://beacon-node-c:1234",
                ],
            },
            id="3 beacon nodes",
        )
    ],
    indirect=True,
)
async def test_get_aggregate_attestation(
    numbers_of_attesting_indices: list[Exception | int],
    best_aggregate_score: int,
    beacon_chain: BeaconChain,
    multi_beacon_node: MultiBeaconNode,
    spec: SpecGloas,
    cli_args: CLIArgs,
) -> None:
    """Tests that the multi-beacon requests aggregate attestations from all beacon nodes
    and returns the one with the highest value.
    """
    with aioresponses() as m:
        for number_of_attesting_indices in numbers_of_attesting_indices:
            if isinstance(number_of_attesting_indices, int):
                bitlist_length = (
                    spec.MAX_VALIDATORS_PER_COMMITTEE * spec.MAX_COMMITTEES_PER_SLOT
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
                _ = await multi_beacon_node.get_aggregate_attestation_v2(
                    attestation_data_root="0x"
                    + AttestationData().hash_tree_root().hex(),
                    slot=beacon_chain.current_slot,
                    committee_index=3,
                )
        else:
            returned_aggregate = await multi_beacon_node.get_aggregate_attestation_v2(
                attestation_data_root="0x" + AttestationData().hash_tree_root().hex(),
                slot=beacon_chain.current_slot,
                committee_index=3,
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
@pytest.mark.parametrize(
    argnames="cli_args",
    argvalues=[
        pytest.param(
            {
                "beacon_node_urls": [
                    "http://beacon-node-a:1234",
                    "http://beacon-node-b:1234",
                    "http://beacon-node-c:1234",
                ],
            },
            id="3 beacon nodes",
        )
    ],
    indirect=True,
)
async def test_get_sync_committee_contribution(
    numbers_of_root_matching_indices: list[Exception | int],
    best_contribution_score: int,
    multi_beacon_node: MultiBeaconNode,
    cli_args: CLIArgs,
    spec: SpecGloas,
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
                _ = await multi_beacon_node.get_sync_committee_contribution(
                    slot=123,
                    subcommittee_index=1,
                    beacon_block_root="0x" + os.urandom(32).hex(),
                )
        else:
            returned_contribution = (
                await multi_beacon_node.get_sync_committee_contribution(
                    slot=123,
                    subcommittee_index=1,
                    beacon_block_root="0x" + os.urandom(32).hex(),
                )
            )
            assert (
                sum(returned_contribution.aggregation_bits) == best_contribution_score
            )
