from unittest import mock

import pytest

from providers import Vero
from providers.bid_selector import BidSelector
from schemas import SchemaBeaconAPI, SchemaShared


def _create_bid(
    value: int, execution_payment: int
) -> SchemaShared.SignedExecutionPayloadBid:
    return SchemaShared.SignedExecutionPayloadBid(
        message=SchemaShared.ExecutionPayloadBid(
            parent_block_hash="0x" + "00" * 32,
            parent_block_root="0x" + "00" * 32,
            block_hash="0x" + "00" * 32,
            prev_randao="0x" + "00" * 32,
            fee_recipient="0x" + "00" * 20,
            gas_limit="30000000",
            builder_index="123",
            slot="1234",
            value=str(value),
            execution_payment=str(execution_payment),
            blob_kzg_commitments=[],
            execution_requests_root="0x" + "00" * 32,
        ),
        signature="0x" + "00" * 96,
    )


@pytest.mark.parametrize(
    argnames=("direct_value", "direct_payment", "p2p_value", "expected_source"),
    argvalues=[
        pytest.param(100, 0, 100, "direct", id="equal-values-prefer-direct"),
        pytest.param(0, 0, 0, "direct", id="zero-values-prefer-direct"),
        pytest.param(60, 40, 100, "direct", id="equal-total-values-prefer-direct"),
        pytest.param(101, 0, 100, "direct", id="higher-direct-value"),
        pytest.param(99, 0, 100, "p2p", id="higher-p2p-value"),
        pytest.param(0, 0, None, "direct", id="only-direct"),
        pytest.param(None, 0, 0, "p2p", id="only-p2p"),
        pytest.param(None, 0, None, None, id="no-bids"),
    ],
)
async def test_get_bid_selects_best_bid(
    vero: Vero,
    direct_value: int | None,
    direct_payment: int,
    p2p_value: int | None,
    expected_source: str | None,
) -> None:
    selector = BidSelector(vero=vero)
    direct_bid = (
        _create_bid(direct_value, direct_payment) if direct_value is not None else None
    )
    p2p_bid = _create_bid(p2p_value, 0) if p2p_value is not None else None
    payload_attributes = SchemaBeaconAPI.PayloadAttributesData(
        proposer_index="1",
        proposal_slot="1234",
        parent_block_root="0x" + "00" * 32,
        parent_block_hash="0x" + "00" * 32,
        payload_attributes={},
    )
    duty = SchemaBeaconAPI.ProposerDuty(
        pubkey="0x" + "00" * 48, validator_index="1", slot="1234"
    )

    with (
        mock.patch.object(
            selector, "_get_payload_attributes_data", return_value=payload_attributes
        ),
        mock.patch.object(
            selector.multi_builder, "get_execution_payload_bid", return_value=direct_bid
        ),
        mock.patch.object(selector, "_get_best_p2p_bid", return_value=p2p_bid),
    ):
        bid = await selector.get_bid(slot=1234, proposer_duty=duty)

    expected_bid = {"direct": direct_bid, "p2p": p2p_bid, None: None}[expected_source]
    assert bid is expected_bid
