import logging
from contextlib import suppress
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
        self.bid_selection_disabled = vero.cli_args.disable_bid_selection
        self.cli_args = vero.cli_args

        self.proposal_slots: set[int] = set()

        self.payload_attributes_events_store: list[
            SchemaBeaconAPI.PayloadAttributesEvent
        ] = []
        self.bid_events_store: list[SchemaBeaconAPI.ExecutionPayloadBidEvent] = []

    async def handle_payload_attributes_event(
        self, event: SchemaBeaconAPI.PayloadAttributesEvent
    ) -> None:
        if int(event.data.proposal_slot) in self.proposal_slots:
            self.logger.info(f"Received payload attributes event: {event}")
            self.payload_attributes_events_store.append(event)
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

        if int(event.data.total_value) < self.cli_args.builder_min_bid:
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
            f"Received bid event with value: {int(event.data.message.value):,}"
        )
        self.bid_events_store.append(event)

    def _get_payload_attributes_data(
        self, slot: int, proposer_duty: SchemaBeaconAPI.ProposerDuty
    ) -> SchemaBeaconAPI.PayloadAttributesData | None:
        pa_events_for_slot = (
            e
            for e in self.payload_attributes_events_store
            if int(e.data.proposal_slot) == slot
        )

        for pa_event in pa_events_for_slot:
            if pa_event.data.proposer_index != proposer_duty.validator_index:
                self.logger.warning(
                    f"Skipping payload attributes event for slot {slot} - does not match proposer duty validator index ({pa_event.data.proposer_index} != {proposer_duty.validator_index})"
                )
                continue

            # TODO with the current implementation, there may be
            #  multiple events for the same slot -> we should probably
            #  only keep the latest event per slot?
            #  hmm I don't know actually, what if it's forked off, or processed
            #  a slot late? Maybe we should use a counter and pick the event
            #  that was emitted the most times?
            self.logger.info("Found payload attributes data")
            return pa_event.data
        return None

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
            ):
                continue

            if bid_event.data.total_value > best_p2p_bid_value:
                best_p2p_bid = bid_event.data
                best_p2p_bid_value = bid_event.data.total_value

        return best_p2p_bid

    def prune(self, *, finished_proposal_slot: int) -> None:
        with suppress(KeyError):
            self.proposal_slots.remove(finished_proposal_slot)
        for pa_event in self.payload_attributes_events_store:
            if int(pa_event.data.proposal_slot) <= finished_proposal_slot:
                self.payload_attributes_events_store.remove(pa_event)
        for bid_event in self.bid_events_store:
            if int(bid_event.data.message.slot) <= finished_proposal_slot:
                self.bid_events_store.remove(bid_event)

    async def get_bid(
        self, slot: int, proposer_duty: SchemaBeaconAPI.ProposerDuty
    ) -> tuple[Builder | None, SchemaShared.SignedExecutionPayloadBid | None]:
        if self.bid_selection_disabled:
            self.logger.info(f"Bid selection disabled, returning None for slot {slot}")
            return None, None

        # TODO consider builder boost factor here

        payload_attributes_data = self._get_payload_attributes_data(
            slot=slot, proposer_duty=proposer_duty
        )
        if not payload_attributes_data:
            self.logger.warning(
                "Unable to fetch bids from builders - did not find corresponding payload attributes data"
            )
            return None, None

        # TODO all the bid value comparison craziness goes here, boost factor, min bid,
        #  Keymanager API overrides

        # TODO Entire bid selection logging - high-level useful data into INFO,
        #  rest into DEBUG, without repeating info.
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
