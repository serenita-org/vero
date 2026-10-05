import logging
from typing import TYPE_CHECKING

from schemas import SchemaBeaconAPI, SchemaShared

if TYPE_CHECKING:
    from .vero import Vero

from .builder import Builder, MultiBuilder


class BidSelector:
    def __init__(self, vero: "Vero") -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

        self.beacon_chain = vero.beacon_chain
        self.multi_builder = MultiBuilder(vero=vero)
        self.bid_selection_disabled = vero.cli_args.enable_bid_selection is False
        self.cli_args = vero.cli_args

        self.proposal_slots: set[int] = set()

        self.payload_attributes_events_store: dict[
            tuple[int, str], SchemaBeaconAPI.PayloadAttributesData
        ] = {}
        self.bid_events_store: list[SchemaBeaconAPI.ExecutionPayloadBidEvent] = []

    async def handle_payload_attributes_event(
        self, event: SchemaBeaconAPI.PayloadAttributesEvent
    ) -> None:
        if int(event.data.proposal_slot) in self.proposal_slots:
            self.logger.info(f"Received payload attributes event: {event}")
            # Keep the latest received attributes for each slot and proposer.
            self.payload_attributes_events_store[
                (int(event.data.proposal_slot), event.data.proposer_index)
            ] = event.data
        else:
            self.logger.debug(f"Ignoring payload attributes event: {event}")

    async def handle_bid_event(
        self, event: SchemaBeaconAPI.ExecutionPayloadBidEvent
    ) -> None:
        if int(event.data.message.slot) not in self.proposal_slots:
            self.logger.debug(
                f"Ignoring bid event for non-proposal slot: {event.data.message.slot}"
            )
            return

        if event.data.total_value < self.cli_args.builder_min_bid:
            self.logger.debug(
                f"Ignoring bid event with value {int(event.data.total_value):,} below configured min bid"
            )
            return

        if event.data.message.fee_recipient.lower() != self.cli_args.fee_recipient:
            self.logger.warning(
                f"Ignoring bid event with fee recipient {event.data.message.fee_recipient} != configured fee recipient {self.cli_args.fee_recipient}"
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
        self, slot: int, payload_attributes_data: SchemaBeaconAPI.PayloadAttributesData
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

            if bid_event.data.total_value > best_p2p_bid_value:
                best_p2p_bid = bid_event.data
                best_p2p_bid_value = bid_event.data.total_value

        return best_p2p_bid

    def prune(self, *, finished_proposal_slot: int) -> None:
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

    async def get_bid(
        self, slot: int, proposer_duty: SchemaBeaconAPI.ProposerDuty
    ) -> tuple[Builder | None, SchemaShared.SignedExecutionPayloadBid | None]:
        if self.bid_selection_disabled:
            self.logger.info(f"Bid selection disabled, returning None for slot {slot}")
            return None, None

        if self.cli_args.builder_boost_factor == 0:
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
            # TODO parametrize/hardcode, similar to block production timeout
            soft_timeout=0.6,
            hard_timeout=1.2,
        )
        best_dir_bid_value = "N/A"
        best_dir_bid_builder, best_direct_bid = None, None
        if result is not None:
            best_dir_bid_builder, best_direct_bid = result
            best_dir_bid_value = f"{best_direct_bid.total_value:,}"
        self.logger.info(f"Best direct bid value: {best_dir_bid_value}")

        best_p2p_bid = self._get_best_p2p_bid(
            slot=slot, payload_attributes_data=payload_attributes_data
        )
        best_p2p_bid_value = "N/A"
        if best_p2p_bid:
            best_p2p_bid_value = f"{best_p2p_bid.total_value:,}"
        self.logger.info(f"Best P2P bid value: {best_p2p_bid_value}")

        # max() returns the first item on ties, so prefer the direct bid.
        best_bid = max(
            (best_direct_bid, best_p2p_bid), key=(lambda x: x.total_value if x else -1)
        )

        self.logger.info(f"Selected best bid: {best_bid}")
        if best_bid == best_direct_bid:
            return best_dir_bid_builder, best_direct_bid
        return None, best_bid
