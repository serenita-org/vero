"""These test the additional behavior of MultiBeaconNode (vs the simple BeaconNode)
when multiple beacon nodes are provided to it. That includes:
- coming to consensus on attestation data to sign
"""

import datetime
import re
from collections import Counter
from functools import partial

import pytest
import pytz
from aiohttp.web_exceptions import HTTPRequestTimeout
from aioresponses import CallbackResult, aioresponses

from providers import MultiBeaconNode
from providers.multi_beacon_node import AttestationConsensusFailure
from schemas import SchemaBeaconAPI
from spec.attestation import AttestationData

# TODO add some more test scenarios
#  Currently the beacon nodes only provide a single response.
#  Test the scenario where they return multiple responses and only
#  come to consensus after some delay (the vc having made multiple
#  API requests).


@pytest.mark.parametrize(
    argnames=["bn_head_block_roots", "head_event"],
    argvalues=[
        pytest.param(
            [
                "0x000000000000000000000000000000000000000000000000000000000000abcd",
                "0x000000000000000000000000000000000000000000000000000000000000abcd",
                "0x000000000000000000000000000000000000000000000000000000000000abcd",
            ],
            None,
            id="Happy path - identical attestation data returned from all beacon nodes",
        ),
        pytest.param(
            [
                "0x000000000000000000000000000000000000000000000000000000000000abcd",
                "0x000000000000000000000000000000000000000000000000000000000000abcd",
                "0x0000000000000000000000000000000000000000000000000000000000005555",
            ],
            None,
            id="2/3 beacon nodes report the same block root, 1 reports a different block root",
        ),
        pytest.param(
            [
                "0x000000000000000000000000000000000000000000000000000000000000abcd",
                "0x000000000000000000000000000000000000000000000000000000000000ffff",
                "0x0000000000000000000000000000000000000000000000000000000000005555",
            ],
            None,
            id="All 3 beacon nodes report different block roots -> method raises an Exception",
        ),
        pytest.param(
            [
                HTTPRequestTimeout(),
                HTTPRequestTimeout(),
                HTTPRequestTimeout(),
            ],
            None,
            id="All 3 beacon node requests time out",
        ),
        pytest.param(
            [
                "0x000000000000000000000000000000000000000000000000000000000000abcd",
                "0x000000000000000000000000000000000000000000000000000000000000abcd",
                "0x000000000000000000000000000000000000000000000000000000000000abcd",
            ],
            SchemaBeaconAPI.HeadEvent(
                slot=1,
                block="0x000000000000000000000000000000000000000000000000000000000000abcd",
                state="0x0",
                epoch_transition=False,
                previous_duty_dependent_root="0x",
                current_duty_dependent_root="0x",
                execution_optimistic=False,
            ),
            id="Head event - beacon nodes report matching data",
        ),
        pytest.param(
            [
                "0x000000000000000000000000000000000000000000000000000000000000abcd",
                "0x000000000000000000000000000000000000000000000000000000000000ffff",
                "0x0000000000000000000000000000000000000000000000000000000000005555",
            ],
            SchemaBeaconAPI.HeadEvent(
                slot=1,
                block="0x000000000000000000000000000000000000000000000000000000000000abcd",
                state="0x0",
                epoch_transition=False,
                previous_duty_dependent_root="0x",
                current_duty_dependent_root="0x",
                execution_optimistic=False,
            ),
            id="Head event - beacon nodes report different data",
        ),
    ],
)
async def test_produce_attestation_data(
    bn_head_block_roots: list[str],
    head_event: SchemaBeaconAPI.HeadEvent,
    multi_beacon_node_three_inited_nodes: MultiBeaconNode,
) -> None:
    """Tests that the multi-beacon requests attestation data from all beacon nodes
    and only returns attestation data if a majority of the beacon nodes
    agree on the latest head block root.
    """
    with aioresponses() as m:
        for block_root in bn_head_block_roots:
            if isinstance(block_root, str):
                _callback = partial(
                    lambda _root, *args, **kwargs: CallbackResult(
                        payload=dict(
                            data=AttestationData(beacon_block_root=_root).to_obj(),
                        ),
                    ),
                    block_root,
                )
                m.get(
                    url=re.compile(
                        r"http://beacon-node-\w:1234/eth/v1/validator/attestation_data",
                    ),
                    callback=_callback,
                )
            elif isinstance(block_root, Exception):
                m.get(
                    url=re.compile(
                        r"http://beacon-node-\w:1234/eth/v1/validator/attestation_data",
                    ),
                    exception=block_root,
                )
            else:
                raise NotImplementedError

        # We expect to fail reaching consensus if none of the returned
        # block roots reaches a majority
        _majority_threshold = (
            len(multi_beacon_node_three_inited_nodes.beacon_nodes) // 2 + 1
        )
        _br_ctr: Counter[str] = Counter()
        for br in bn_head_block_roots:
            if isinstance(br, Exception):
                continue
            _br_ctr[br] += 1

        if all(
            block_root_count < _majority_threshold
            for block_root_count in _br_ctr.values()
        ):
            with pytest.raises(
                AttestationConsensusFailure,
                match="Failed to reach consensus on attestation data",
            ):
                _ = await multi_beacon_node_three_inited_nodes.produce_attestation_data(
                    deadline=datetime.datetime.now(tz=pytz.UTC)
                    + datetime.timedelta(seconds=0.1),
                    slot=123,
                    committee_index=3,
                    head_event=head_event,
                )
            return

        # We expect to reach consensus on attestation data here
        att_data = await multi_beacon_node_three_inited_nodes.produce_attestation_data(
            deadline=datetime.datetime.now(tz=pytz.UTC) + datetime.timedelta(seconds=1),
            slot=123,
            committee_index=3,
            head_event=head_event,
        )
        assert att_data.beacon_block_root.to_obj() in bn_head_block_roots

        # We should only be able to reach consensus if a majority
        # of beacon nodes returns the same block root
        assert any(
            block_root_count >= _majority_threshold
            for block_root_count in _br_ctr.values()
        )

        # And we expect to receive exactly that block root that has a majority
        assert att_data.beacon_block_root.to_obj() == next(
            br for br, count in _br_ctr.items() if count >= _majority_threshold
        )
