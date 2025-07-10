import asyncio
import datetime
import logging
import time

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from schemas import SchemaBeaconAPI

from .beacon_chain import BeaconChain
from .multi_beacon_node import MultiBeaconNode


class AttestationDataProvider:
    def __init__(
        self,
        multi_beacon_node: MultiBeaconNode,
        beacon_chain: BeaconChain,
        scheduler: AsyncIOScheduler,
    ):
        self.logger = logging.getLogger("AttestationData")

        self.multi_beacon_node = multi_beacon_node
        self.beacon_chain = beacon_chain

        self._timeout_att_data_for_head_event = 0.5
        self._timeout_confirm_checkpoints_att_data_for_head_event = 1.0

        scheduler.add_job(
            self.prune,
            "interval",
            minutes=10,
            next_run_time=datetime.datetime.now(tz=datetime.UTC),
            id=f"{self.__class__.__name__}.prune",
        )

        self.source_checkpoint_confirmation_cache: dict[
            int, SchemaBeaconAPI.Checkpoint
        ] = dict()
        self.target_checkpoint_confirmation_cache: dict[
            int, SchemaBeaconAPI.Checkpoint
        ] = dict()

    async def _confirm_checkpoints(
        self,
        source_cp: SchemaBeaconAPI.Checkpoint,
        target_cp: SchemaBeaconAPI.Checkpoint,
        slot: int,
    ) -> None:
        source_epoch, target_epoch = (
            int(source_cp.epoch),
            int(target_cp.epoch),
        )
        if source_cp == self.source_checkpoint_confirmation_cache.get(
            source_epoch
        ) and target_cp == self.target_checkpoint_confirmation_cache.get(target_epoch):
            self.logger.debug(
                f"Checkpoints for epochs {source_epoch} => {target_epoch} confirmed from cache"
            )
            return

        self.logger.info(f"Confirming checkpoints for {source_epoch} => {target_epoch}")

        await self.multi_beacon_node.wait_for_checkpoints(
            slot=slot,
            expected_source_cp=source_cp,
            expected_target_cp=target_cp,
        )
        self.source_checkpoint_confirmation_cache[source_epoch] = source_cp
        self.target_checkpoint_confirmation_cache[target_epoch] = target_cp
        self.logger.info("Checkpoints confirmed")

    async def _produce_attestation_data_without_expected_head_block_root(
        self, slot: int
    ) -> SchemaBeaconAPI.AttestationData:
        # We ask all beacon nodes to produce AttestationData,
        # requiring a threshold of them to agree on the head of the chain.
        next_slot_start_ts = self.beacon_chain.get_timestamp_for_slot(slot + 1)
        att_data = await asyncio.wait_for(
            self.multi_beacon_node.produce_attestation_data_without_head_event(
                slot=slot,
            ),
            timeout=next_slot_start_ts - time.time(),
        )

        await asyncio.wait_for(
            self._confirm_checkpoints(
                source_cp=att_data.source,
                target_cp=att_data.target,
                slot=slot,
            ),
            timeout=next_slot_start_ts - time.time(),
        )
        return att_data

    async def produce_attestation_data(
        self,
        slot: int,
        head_event_block_root: str | None,
    ) -> SchemaBeaconAPI.AttestationData:
        """
        Produces AttestationData for the given slot.

        If a block root is provided from a head event, we attempt to produce
        AttestationData with that block root.

        We check the resulting AttestationData's FFG checkpoints among
        all connected beacon nodes.
        """
        if head_event_block_root is None:
            return (
                await self._produce_attestation_data_without_expected_head_block_root(
                    slot=slot
                )
            )

        # We have an expected head block root from a head event.
        # Fetch the full AttestationData for the given block root
        # from the fastest beacon node. Times out in 500 ms.
        try:
            att_data = await asyncio.wait_for(
                self.multi_beacon_node.wait_for_attestation_data(
                    expected_head_block_root=head_event_block_root,
                    slot=slot,
                ),
                timeout=self._timeout_att_data_for_head_event,
            )
        except TimeoutError:
            # We only have a limited amount of time to attest. If we are unable to retrieve
            # the corresponding full AttestationData for the expected head block root quickly,
            # use the fallback behavior of attesting without an expected head block root.
            self.logger.warning(
                f"Timed out waiting for AttestationData for head block root: {head_event_block_root}"
            )
            return (
                await self._produce_attestation_data_without_expected_head_block_root(
                    slot=slot
                )
            )
        else:
            self.logger.debug("AttestationData received, confirming checkpoints")

        # We have a full AttestationData object at this point. The only thing left is
        # to confirm the FFG checkpoints. This part also has a timeout to make sure
        # we still at least have a chance to attest on time if we're unable to confirm
        # the checkpoints from the AttestationData. Times out in 1000 ms.
        try:
            await asyncio.wait_for(
                self._confirm_checkpoints(
                    source_cp=att_data.source,
                    target_cp=att_data.target,
                    slot=slot,
                ),
                timeout=self._timeout_confirm_checkpoints_att_data_for_head_event,
            )
        except TimeoutError:
            # Failed to confirm the checkpoints for the AttestationData we retrieved.
            # --> The head event we received may be for a buggy chain. We can still
            #     attempt to attest without an expected head block root.
            self.logger.debug(
                f"Failed to confirm checkpoints {att_data.source=}, {att_data.target=}"
            )
            return (
                await self._produce_attestation_data_without_expected_head_block_root(
                    slot=slot
                )
            )
        else:
            return att_data

    def prune(self) -> None:
        # Only keep up to 3 most recent checkpoints in checkpoint confirmation cache
        self.source_checkpoint_confirmation_cache = dict(
            sorted(
                self.source_checkpoint_confirmation_cache.items(),
                key=lambda item: item[0],
                reverse=True,
            )[:3]
        )
        self.target_checkpoint_confirmation_cache = dict(
            sorted(
                self.target_checkpoint_confirmation_cache.items(),
                key=lambda item: item[0],
                reverse=True,
            )[:3]
        )
