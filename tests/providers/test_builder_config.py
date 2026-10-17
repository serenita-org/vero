import asyncio
from unittest import mock

import msgspec
import pytest
from aioresponses import aioresponses

from args import CLIArgs
from providers import Keymanager, MultiBeaconNode, MultiBuilder, SignatureProvider, Vero
from schemas import SchemaBeaconAPI, SchemaBuilderAPI, SchemaShared
from schemas.keymanager_api import BuilderConfig, BuilderEntry
from schemas.validator import ValidatorIndexPubkey
from tests.providers.test_multi_builder import _create_bid

pytestmark = pytest.mark.parametrize("enable_keymanager_api", [True], indirect=True)


async def test_per_key_builders_and_authentication(
    keymanager: Keymanager,
    vero: Vero,
    signature_provider: SignatureProvider,
    validators: list[ValidatorIndexPubkey],
) -> None:
    pubkey = validators[0].pubkey
    keymanager.set_builder_config(
        pubkey,
        BuilderConfig(
            builders=[
                BuilderEntry(url="https://builder.example", auth_data="0xaa"),
                BuilderEntry(url="https://builder.example", auth_data="0xbb"),
            ]
        ),
    )
    duty = SchemaBeaconAPI.ProposerDuty(pubkey=pubkey, validator_index="1", slot="123")
    async with MultiBuilder(vero, keymanager=keymanager) as builders:
        await builders.cache_bid_request_auth_data(duty, signature_provider)
        entries = builders.get_builder_entries(pubkey)
        assert len(entries) == 2
        assert entries[0][0] is not entries[1][0]
        for builder, entry in entries:
            signed_auth = builder.get_signed_builder_request_auth(123, pubkey)
            assert signed_auth.message.data == entry.auth_data
            assert signed_auth.message.slot == "123"
        # A changed configuration takes effect for the same slot, without old auth reuse.
        keymanager.set_builder_config(
            pubkey,
            BuilderConfig(
                builders=[
                    BuilderEntry(url="https://builder.example", auth_data="0xcc"),
                ]
            ),
        )
        await builders.cache_bid_request_auth_data(duty, signature_provider)
        builder, _ = builders.get_builder_entries(pubkey)[0]
        assert (
            builder.get_signed_builder_request_auth(123, pubkey).message.data == "0xcc"
        )
        old_builders = [b for b, _ in entries]
        builders.prune(finished_proposal_slot=123)
        # Session closes are scheduled through the task manager.
        await asyncio.sleep(0)
        assert all(b.client_session.closed for b in old_builders)
        assert not builder.client_session.closed
        keymanager.set_builder_config(pubkey, BuilderConfig(builders=[]))
        assert builders.get_builder_entries(pubkey) == []


@pytest.mark.parametrize(
    ("min_bid", "allowlisted_index", "fallback_payment", "expected_value"),
    [
        ("0", "123", 0, 80),
        ("81", "123", 0, 100),
        ("0", "999", 0, 100),
        ("81", "123", 1, None),
    ],
)
async def test_configured_bid_selection(
    keymanager: Keymanager,
    vero: Vero,
    signature_provider: SignatureProvider,
    multi_beacon_node: MultiBeaconNode,
    validators: list[ValidatorIndexPubkey],
    mocked_responses: aioresponses,
    min_bid: str,
    allowlisted_index: str,
    fallback_payment: int,
    expected_value: int | None,
) -> None:
    pubkey = validators[0].pubkey
    builder_pubkey = "0x" + "ab" * 48
    # Reject the second bid despite its much higher in-protocol payment.
    # A valid third builder remains available if the preferred bid is filtered out.
    keymanager.set_builder_config(
        pubkey,
        BuilderConfig(
            builders=[
                BuilderEntry(
                    url="https://preferred.example",
                    min_bid=min_bid,
                    builder_boost_factor="200",
                    builder_pubkeys=[builder_pubkey],
                ),
                BuilderEntry(
                    url="https://other.example",
                    max_execution_payment="0",
                    builder_boost_factor="100",
                ),
                BuilderEntry(url="https://fallback.example", max_execution_payment="0"),
            ]
        ),
    )
    duty = SchemaBeaconAPI.ProposerDuty(pubkey=pubkey, validator_index="1", slot="123")
    async with MultiBuilder(
        vero, keymanager, multi_beacon_node, signature_provider
    ) as builders:
        with mock.patch.object(
            multi_beacon_node,
            "get_builders",
            return_value={builder_pubkey: allowlisted_index},
        ):
            await builders.cache_bid_request_auth_data(duty, signature_provider)
        responses = mocked_responses
        for url, bid in [
            ("https://preferred.example", _create_bid(80)),
            ("https://other.example", _create_bid(10_000, 1_000)),
            ("https://fallback.example", _create_bid(100, fallback_payment)),
        ]:
            responses.post(
                url
                + f"/eth/v1/builder/execution_payload_bid/123/{'0x' + 'aa' * 32}/{'0x' + 'bb' * 32}/{pubkey}",
                body=msgspec.json.encode(
                    SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                        version=SchemaShared.ForkVersion.GLOAS,
                        data=bid,
                    )
                ),
            )
        result = await builders.get_execution_payload_bid(
            slot=123,
            parent_hash="0x" + "aa" * 32,
            parent_root="0x" + "bb" * 32,
            proposer_pubkey=pubkey,
            fork_version=SchemaShared.ForkVersion.GLOAS,
            soft_timeout=0.1,
            hard_timeout=0.2,
        )
        if expected_value is None:
            assert result is None
        else:
            assert result is not None
            assert int(result[1].message.value) == expected_value


@pytest.mark.parametrize(
    ("max_execution_payment", "execution_payment"),
    [("0", 0), ("0", 1), ("12", 11), ("12", 12), ("12", 13), ("12", 1000)],
)
async def test_custom_fee_recipient_and_preferences(
    keymanager: Keymanager,
    vero: Vero,
    signature_provider: SignatureProvider,
    validators: list[ValidatorIndexPubkey],
    cli_args: CLIArgs,
    mocked_responses: aioresponses,
    max_execution_payment: str,
    execution_payment: int,
) -> None:
    pubkey = validators[0].pubkey
    keymanager.set_builder_config(
        pubkey,
        BuilderConfig(
            builders=[
                BuilderEntry(
                    url="https://builder.example",
                    max_execution_payment=max_execution_payment,
                    min_bid=str(100 + execution_payment),
                ),
            ]
        ),
    )
    custom_recipient = "0x" + "bb" * 20
    keymanager.set_fee_recipient(pubkey, custom_recipient)
    async with MultiBuilder(vero, keymanager=keymanager) as builders:
        await builders.cache_bid_request_auth_data(
            SchemaBeaconAPI.ProposerDuty(
                pubkey=pubkey, validator_index="1", slot="123"
            ),
            signature_provider,
        )
        builder, entry = builders.get_builder_entries(pubkey)[0]
        with mock.patch.object(builder, "make_request") as request:
            await builders.submit_builder_preferences(
                123, pubkey, SchemaShared.ForkVersion.GLOAS
            )
            body = msgspec.json.decode(request.call_args.kwargs["data"])
            assert body["preferences"]["max_execution_payment"] == max_execution_payment
        bid = _create_bid(100, execution_payment)
        bid.message.fee_recipient = custom_recipient
        responses = mocked_responses
        responses.post(
            f"https://builder.example/eth/v1/builder/execution_payload_bid/123/{bid.message.parent_block_hash}/{bid.message.parent_block_root}/{pubkey}",
            body=msgspec.json.encode(
                SchemaBuilderAPI.GetExecutionPayloadBidResponse(
                    version=SchemaShared.ForkVersion.GLOAS,
                    data=bid,
                )
            ),
        )
        bid_request = builder.get_execution_payload_bid(
            slot=123,
            parent_hash=bid.message.parent_block_hash,
            parent_root=bid.message.parent_block_root,
            proposer_pubkey=pubkey,
            fork_version=SchemaShared.ForkVersion.GLOAS,
            soft_timeout=0.1,
            hard_timeout=0.2,
            config=entry,
            fee_recipient=custom_recipient,
        )
        if execution_payment > int(max_execution_payment):
            with pytest.raises(
                ValueError, match="exceeds configured max execution payment"
            ):
                await bid_request
        else:
            result = await bid_request
            assert result is not None
            assert int(result[1].message.execution_payment) == execution_payment
