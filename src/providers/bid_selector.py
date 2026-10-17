import logging
from typing import TYPE_CHECKING

from schemas import SchemaBeaconAPI, SchemaShared

if TYPE_CHECKING:
    from .vero import Vero

from .builder import Builder, MultiBuilder
from .builder_config import bid_score


class BidSelector:
    def __init__(self, multi_builder: MultiBuilder, vero: "Vero") -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

        self.beacon_chain = vero.beacon_chain
        self.multi_builder = multi_builder
        self.bid_selection_disabled = vero.cli_args.enable_bid_selection is False
        self.cli_args = vero.cli_args
        self._get_bid_soft_timeout = self.cli_args.builder_bid_request_timeout / 1_000

        self.proposal_slots: set[int] = set()
        self.selected_bid_boost_factors: dict[tuple[int, str], str] = {}

        self.payload_attributes_events_store: dict[
            tuple[int, str], SchemaBeaconAPI.PayloadAttributesData
        ] = {}
        self.bid_events_store: list[SchemaBeaconAPI.ExecutionPayloadBidEvent] = []

    async def handle_payload_attributes_event(
        self, event: SchemaBeaconAPI.PayloadAttributesEvent
    ) -> None:
        if int(event.data.proposal_slot) not in self.proposal_slots:
            self.logger.debug(
                f"Ignoring payload attributes event for non-proposal slot: {event}"
            )
            return

        self.logger.debug(f"Received payload attributes event: {event}")
        # Keep the latest received attributes for each slot and proposer.
        self.payload_attributes_events_store[
            (int(event.data.proposal_slot), event.data.proposer_index)
        ] = event.data

    async def handle_bid_event(
        self, event: SchemaBeaconAPI.ExecutionPayloadBidEvent
    ) -> None:
        if int(event.data.message.slot) not in self.proposal_slots:
            self.logger.debug(
                f"Ignoring bid event for non-proposal slot: {event.data.message.slot}"
            )
            return

        self.logger.info(
            f"Received P2P bid with value: {int(event.data.message.value):,}"
        )
        self.bid_events_store.append(event)

    def _get_payload_attributes_data(
        self, slot: int, proposer_duty: SchemaBeaconAPI.ProposerDuty
    ) -> SchemaBeaconAPI.PayloadAttributesData | None:
        return self.payload_attributes_events_store.get(
            (slot, proposer_duty.validator_index)
        )

    def _get_best_p2p_bid(
        self,
        slot: int,
        payload_attributes_data: SchemaBeaconAPI.PayloadAttributesData,
        min_bid: int = 0,
        fee_recipient: str | None = None,
    ) -> SchemaShared.SignedExecutionPayloadBid | None:
        best_p2p_bid = None
        best_p2p_bid_value = -1
        for bid_event in self.bid_events_store:
            if int(bid_event.data.message.slot) != slot:
                continue

            if (
                bid_event.data.message.parent_block_root
                != payload_attributes_data.parent_block_root
                # intentionally not requiring parent_block_hash
                # to match because the connected beacon nodes
                # may have differing opinions on whether
                # we're building on top of EMPTY/FULL
            ):
                continue

            if bid_event.data.total_value < min_bid:
                continue
            if (
                fee_recipient is not None
                and bid_event.data.message.fee_recipient.lower()
                != fee_recipient.lower()
            ):
                continue

            if bid_event.data.total_value > best_p2p_bid_value:
                best_p2p_bid = bid_event.data
                best_p2p_bid_value = bid_event.data.total_value

        return best_p2p_bid

    def prune(self, *, finished_proposal_slot: int) -> None:
        self.selected_bid_boost_factors = {
            key: factor
            for key, factor in self.selected_bid_boost_factors.items()
            if key[0] > finished_proposal_slot
        }
        self.proposal_slots.difference_update(
            {slot for slot in self.proposal_slots if slot <= finished_proposal_slot}
        )
        for key in list(self.payload_attributes_events_store):
            if key[0] <= finished_proposal_slot:
                del self.payload_attributes_events_store[key]
        self.bid_events_store = [
            event
            for event in self.bid_events_store
            if int(event.data.message.slot) > finished_proposal_slot
        ]

    def _select_best_bid(
        self,
        p2p_bid: SchemaShared.SignedExecutionPayloadBid | None,
        direct_bid: SchemaShared.SignedExecutionPayloadBid | None,
        direct_bid_builder: Builder | None,
        p2p_boost_factor: int = 100,
        direct_boost_factor: int = 100,
        direct_max_execution_payment: int = 0,
    ) -> tuple[
        SchemaShared.SignedExecutionPayloadBid | None,
        str | None,
        Builder | None,
    ]:
        # Enforce the configured limit before comparing the remaining candidates.
        if (
            direct_bid is not None
            and int(direct_bid.message.execution_payment) > direct_max_execution_payment
        ):
            direct_bid = None
            direct_bid_builder = None

        if direct_bid is None and p2p_bid is None:
            return None, None, None

        if direct_bid is None:
            return p2p_bid, "p2p", None

        if p2p_bid is None:
            return direct_bid, "direct", direct_bid_builder

        if bid_score(direct_bid.total_value, direct_boost_factor) >= bid_score(
            p2p_bid.total_value, p2p_boost_factor
        ):
            return direct_bid, "direct", direct_bid_builder

        return p2p_bid, "p2p", None

    async def get_best_bid(
        self, slot: int, proposer_duty: SchemaBeaconAPI.ProposerDuty
    ) -> tuple[Builder | None, SchemaShared.SignedExecutionPayloadBid | None]:
        if self.bid_selection_disabled:
            self.logger.info(f"Bid selection disabled, returning None for slot {slot}")
            return None, None

        config = self.multi_builder.get_config(proposer_duty.pubkey)
        if int(config.builder_boost_factor) == 0 and all(
            int(e.builder_boost_factor) == 0 for e in config.builders
        ):
            self.logger.info(
                f"Builder boost factor is 0, returning None for slot {slot}"
            )
            return None, None

        payload_attributes_data = self._get_payload_attributes_data(
            slot=slot, proposer_duty=proposer_duty
        )
        if not payload_attributes_data:
            self.logger.warning(
                "Unable to fetch bids from builders - did not find corresponding payload attributes data"
            )
            return None, None

        result = await self.multi_builder.get_execution_payload_bid(
            slot=slot,
            parent_hash=payload_attributes_data.parent_block_hash,
            parent_root=payload_attributes_data.parent_block_root,
            proposer_pubkey=proposer_duty.pubkey,
            fork_version=self.beacon_chain.current_fork_version,
            soft_timeout=self._get_bid_soft_timeout,
            hard_timeout=self._get_bid_soft_timeout + 0.1,
            config=config,
        )
        best_dir_bid_value = "N/A"
        best_dir_bid_builder, best_direct_bid = None, None
        if result is not None:
            best_dir_bid_builder, best_direct_bid = result
            best_dir_bid_value = f"{best_direct_bid.total_value:,}"
        self.logger.info(f"Best direct bid value: {best_dir_bid_value}")

        best_p2p_bid = self._get_best_p2p_bid(
            slot=slot,
            payload_attributes_data=payload_attributes_data,
            min_bid=int(config.min_bid),
            fee_recipient=self.multi_builder.get_fee_recipient(proposer_duty.pubkey),
        )
        best_p2p_bid_value = "N/A"
        if best_p2p_bid:
            best_p2p_bid_value = f"{best_p2p_bid.total_value:,}"
        self.logger.info(f"Best P2P bid value: {best_p2p_bid_value}")

        direct_boost = config.builder_boost_factor
        direct_max_payment = str(self.cli_args.builder_max_execution_payment)
        if best_dir_bid_builder is not None:
            for entry in config.builders:
                if (entry.url, entry.auth_data) == (
                    best_dir_bid_builder.url,
                    best_dir_bid_builder.auth_data,
                ):
                    direct_boost = entry.builder_boost_factor
                    direct_max_payment = entry.max_execution_payment
                    break
        bid, source, builder = self._select_best_bid(
            best_p2p_bid,
            best_direct_bid,
            best_dir_bid_builder,
            p2p_boost_factor=int(config.builder_boost_factor),
            direct_boost_factor=int(direct_boost),
            direct_max_execution_payment=int(direct_max_payment),
        )

        if bid is None:
            self.logger.info("No bid selected")
            return None, None

        self.selected_bid_boost_factors[(slot, proposer_duty.pubkey)] = (
            direct_boost if source == "direct" else config.builder_boost_factor
        )
        self.logger.info(f"Returning best bid ({source}): {bid}")
        return builder, bid
