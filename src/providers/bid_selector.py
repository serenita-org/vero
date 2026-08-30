import logging

from schemas import SchemaBeaconAPI, SchemaShared

from .builder import MultiBuilder


class BidSelector:
    def __init__(self, vero: "Vero") -> None:
        self.logger = logging.getLogger(self.__class__.__name__)

        self.beacon_chain = vero.beacon_chain
        self.multi_builder = MultiBuilder(vero=vero)

        # TODO prune
        self.proposal_slots: set[int] = set()

        # TODO prune
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
        if int(event.data.message.slot) in self.proposal_slots:
            self.logger.info(f"Received bid event: {event}")
            self.bid_events_store.append(event)
        else:
            self.logger.debug(f"Ignoring bid event: {event}")

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

    async def get_bid(
        self, slot: int, proposer_duty: SchemaBeaconAPI.ProposerDuty
    ) -> SchemaShared.SignedExecutionPayloadBid | None:
        payload_attributes_data = self._get_payload_attributes_data(
            slot=slot, proposer_duty=proposer_duty
        )
        if not payload_attributes_data:
            self.logger.warning(
                "Unable to fetch bids from builders - did not find corresponding payload attributes data"
            )
            return None

        # TODO all the bid value comparison craziness goes here, boost factor, min bid,
        #  Keymanager API overrides
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

        self.logger.info(
            f"Best P2P bid value: {best_p2p_bid_value if best_p2p_bid else 'N/A'}"
        )

        best_direct_bid = await self.multi_builder.get_execution_payload_bid(
            slot=slot,
            parent_hash=payload_attributes_data.parent_block_hash,
            parent_root=payload_attributes_data.parent_block_root,
            proposer_pubkey=proposer_duty.pubkey,
            fork_version=self.beacon_chain.current_fork_version,
            # TODO parametrize/hardcode, similar to block production timeout
            soft_timeout=0.1,
            hard_timeout=0.2,
        )

        self.logger.info(
            f"Best direct bid value: {best_direct_bid.total_value if best_direct_bid else 'N/A'}"
        )

        # TODO which is picked if they have the same value? and which should be?
        #  potuz said direct bid should be preferred in this case on Discord
        best_bid = max(
            (best_p2p_bid, best_direct_bid), key=(lambda x: x.total_value if x else -1)
        )

        self.logger.info(f"Selected best bid: {best_bid}")

        return best_bid
