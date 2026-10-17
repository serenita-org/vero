from unittest import mock

import pytest

from providers import Keymanager, MultiBuilder, SignatureProvider, Vero
from providers.bid_selector import BidSelector
from schemas import SchemaBeaconAPI, SchemaShared
from schemas.validator import ValidatorIndexPubkey


def _create_bid(
    value: int, execution_payment: int
) -> SchemaShared.SignedExecutionPayloadBid:
    return SchemaShared.SignedExecutionPayloadBid(
        message=SchemaShared.ExecutionPayloadBid(
            parent_block_hash="0x" + "aa" * 32,
            parent_block_root="0x" + "bb" * 32,
            block_hash="0x" + "cc" * 32,
            prev_randao="0x" + "rr" * 32,
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
async def test_get_best_bid_selects_best_bid(
    multi_builder: MultiBuilder,
    vero: Vero,
    direct_value: int | None,
    direct_payment: int,
    p2p_value: int | None,
    expected_source: str | None,
) -> None:
    selector = BidSelector(multi_builder=multi_builder, vero=vero)
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

    get_execution_payload_bid_return_value = None
    if direct_bid:
        get_execution_payload_bid_return_value = (None, direct_bid)

    with (
        mock.patch.object(
            selector, "_get_payload_attributes_data", return_value=payload_attributes
        ),
        mock.patch.object(
            selector.multi_builder,
            "get_execution_payload_bid",
            return_value=get_execution_payload_bid_return_value,
        ),
        mock.patch.object(selector, "_get_best_p2p_bid", return_value=p2p_bid),
    ):
        result = await selector.get_best_bid(slot=1234, proposer_duty=duty)

    expected_bid = {"direct": direct_bid, "p2p": p2p_bid, None: None}[expected_source]
    _builder, bid = result
    assert bid is expected_bid


async def test_get_bid_zero_boost_skips_bid_selection(
    multi_builder: MultiBuilder, vero: Vero
) -> None:
    selector = BidSelector(multi_builder=multi_builder, vero=vero)
    duty = SchemaBeaconAPI.ProposerDuty(
        pubkey="0x" + "00" * 48, validator_index="1", slot="1234"
    )
    with (
        mock.patch.object(selector.cli_args, "builder_boost_factor", 0),
        mock.patch.object(selector, "_get_payload_attributes_data") as get_attributes,
        mock.patch.object(
            selector.multi_builder, "get_execution_payload_bid"
        ) as get_direct_bid,
        mock.patch.object(selector, "_get_best_p2p_bid") as get_p2p_bid,
    ):
        assert await selector.get_best_bid(slot=1234, proposer_duty=duty) == (
            None,
            None,
        )

        get_attributes.assert_not_called()
        get_direct_bid.assert_not_called()
        get_p2p_bid.assert_not_called()


@pytest.mark.parametrize("p2p_available", [True, False])
async def test_bid_comparison_defaults_to_no_trusted_payment(
    multi_builder: MultiBuilder, vero: Vero, p2p_available: bool
) -> None:
    selector = BidSelector(multi_builder, vero)
    direct = _create_bid(1_000, 1_000)
    p2p = _create_bid(2, 0) if p2p_available else None
    bid, source, _ = selector._select_best_bid(p2p, direct, None)
    assert bid is p2p
    assert source == ("p2p" if p2p_available else None)


@pytest.mark.parametrize("enable_keymanager_api", [True], indirect=True)
@pytest.mark.parametrize(
    (
        "direct_value",
        "payment",
        "entry_boost",
        "key_boost",
        "p2p_value",
        "expected_source",
    ),
    [
        (100, 0, "200", "100", 150, "direct"),
        (100, 0, "50", "100", 90, "p2p"),
        (100, 1000, "100", "100", 200, "p2p"),
        (300, 1000, "100", "100", 200, "p2p"),
        (100, 0, "200", "0", 10, "direct"),
    ],
)
async def test_per_key_bid_weighting(
    multi_builder: MultiBuilder,
    vero: Vero,
    keymanager: Keymanager,
    signature_provider: SignatureProvider,
    validators: list[ValidatorIndexPubkey],
    direct_value: int,
    payment: int,
    entry_boost: str,
    key_boost: str,
    p2p_value: int,
    expected_source: str | None,
) -> None:
    from schemas.keymanager_api import BuilderConfig, BuilderEntry

    pubkey = validators[0].pubkey
    multi_builder.keymanager = keymanager
    keymanager.set_builder_config(
        pubkey,
        BuilderConfig(
            builder_boost_factor=key_boost,
            builders=[
                BuilderEntry(
                    url="https://builder.example",
                    max_execution_payment="0",
                    builder_boost_factor=entry_boost,
                )
            ],
        ),
    )
    builder, _ = multi_builder.get_builder_entries(pubkey)[0]
    selector = BidSelector(multi_builder, vero)
    direct = _create_bid(direct_value, payment)
    p2p = _create_bid(p2p_value, 0)
    duty = SchemaBeaconAPI.ProposerDuty(pubkey=pubkey, validator_index="1", slot="1234")
    attributes = SchemaBeaconAPI.PayloadAttributesData(
        proposer_index="1",
        proposal_slot="1234",
        parent_block_root=p2p.message.parent_block_root,
        parent_block_hash=p2p.message.parent_block_hash,
        payload_attributes={},
    )
    with (
        mock.patch.object(
            selector, "_get_payload_attributes_data", return_value=attributes
        ),
        mock.patch.object(
            multi_builder, "get_execution_payload_bid", return_value=(builder, direct)
        ),
        mock.patch.object(selector, "_get_best_p2p_bid", return_value=p2p),
    ):
        _, selected = await selector.get_best_bid(1234, duty)
    assert selected is {"direct": direct, "p2p": p2p, None: None}[expected_source]
    if selected is not None:
        assert selector.selected_bid_boost_factors[(1234, pubkey)] == (
            entry_boost if expected_source == "direct" else key_boost
        )


@pytest.mark.parametrize("enable_keymanager_api", [True], indirect=True)
async def test_p2p_filter_uses_current_per_key_defaults(
    multi_builder: MultiBuilder,
    vero: Vero,
    keymanager: Keymanager,
    signature_provider: SignatureProvider,
    validators: list[ValidatorIndexPubkey],
) -> None:
    from schemas.keymanager_api import BuilderConfig

    pubkey = validators[0].pubkey
    multi_builder.keymanager = keymanager
    selector = BidSelector(multi_builder, vero)
    selector.proposal_slots.add(1234)
    vero.cli_args.builder_min_bid = 100
    bid = _create_bid(50, 0)
    recipient = "0x" + "ab" * 20
    bid.message.fee_recipient = recipient
    await selector.handle_bid_event(
        SchemaBeaconAPI.ExecutionPayloadBidEvent(
            version=SchemaShared.ForkVersion.GLOAS,
            data=bid,
        )
    )
    keymanager.set_builder_config(pubkey, BuilderConfig(min_bid="40", builders=[]))
    keymanager.set_fee_recipient(pubkey, recipient)
    duty = SchemaBeaconAPI.ProposerDuty(pubkey=pubkey, validator_index="1", slot="1234")
    selector.payload_attributes_events_store[(1234, "1")] = (
        SchemaBeaconAPI.PayloadAttributesData(
            proposer_index="1",
            proposal_slot="1234",
            parent_block_root=bid.message.parent_block_root,
            parent_block_hash=bid.message.parent_block_hash,
            payload_attributes={},
        )
    )
    assert (await selector.get_best_bid(1234, duty))[1] is bid
    keymanager.set_builder_config(pubkey, BuilderConfig(min_bid="60", builders=[]))
    assert (await selector.get_best_bid(1234, duty))[1] is None
