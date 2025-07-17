import asyncio
import datetime
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from schemas import SchemaBeaconAPI

from .multi_beacon_node import MultiBeaconNode


class AttestationDataProvider:
    def __init__(
        self,
        multi_beacon_node: MultiBeaconNode,
        scheduler: AsyncIOScheduler,
    ):
        self.logger = logging.getLogger("AttestationData")

        self.multi_beacon_node = multi_beacon_node

        self._timeout_head_event_att_data = 0.5
        self._timeout_head_event_checkpoint_confirmation = 1.0

        scheduler.add_job(
            self.prune,
            "interval",
            minutes=10,
            next_run_time=datetime.datetime.now(tz=datetime.UTC),
            id=f"{self.__class__.__name__}.prune",
        )

        self.source_checkpoint_confirmation_cache: dict[
            str, SchemaBeaconAPI.Checkpoint
        ] = dict()
        self.target_checkpoint_confirmation_cache: dict[
            str, SchemaBeaconAPI.Checkpoint
        ] = dict()

    def _cache_checkpoints(
        self, source: SchemaBeaconAPI.Checkpoint, target: SchemaBeaconAPI.Checkpoint
    ) -> None:
        self.source_checkpoint_confirmation_cache[source.epoch] = source
        self.target_checkpoint_confirmation_cache[target.epoch] = target

    async def _confirm_finality_checkpoints(
        self,
        source: SchemaBeaconAPI.Checkpoint,
        target: SchemaBeaconAPI.Checkpoint,
        slot: int,
    ) -> None:
        if source == self.source_checkpoint_confirmation_cache.get(
            source.epoch
        ) and target == self.target_checkpoint_confirmation_cache.get(target.epoch):
            self.logger.debug(
                f"Finality checkpoints confirmed from cache ({source=}, {target=})"
            )
            return

        self.logger.info(f"Confirming finality checkpoints {source=} => {target=}")

        await self.multi_beacon_node.wait_for_checkpoints(
            slot=slot,
            expected_source_cp=source,
            expected_target_cp=target,
        )
        self._cache_checkpoints(source=source, target=target)

    async def _produce_attestation_data_without_expected_head_block_root(
        self, slot: int
    ) -> SchemaBeaconAPI.AttestationData:
        # We ask all beacon nodes to produce AttestationData,
        # requiring a threshold of them to agree on it.
        att_data = (
            await self.multi_beacon_node.produce_attestation_data_without_head_event(
                slot=slot,
            )
        )
        # No need to confirm the checkpoints in att_data, those were already confirmed
        # within `produce_attestation_data_without_head_event` which requires
        # a full AttestationData match among (incl. checkpoints)
        self._cache_checkpoints(source=att_data.source, target=att_data.target)
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

        We check the resulting AttestationData's finality checkpoints among
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
        # from the fastest beacon node.
        try:
            att_data = await asyncio.wait_for(
                self.multi_beacon_node.wait_for_attestation_data(
                    expected_head_block_root=head_event_block_root,
                    slot=slot,
                ),
                timeout=self._timeout_head_event_att_data,
            )
        except TimeoutError:
            # We only have a limited amount of time to attest. If we are unable to retrieve
            # the corresponding full AttestationData for the expected head block root quickly,
            # use the fallback behavior of attesting without an expected head block root.
            self.logger.warning(
                f"Timed out waiting for AttestationData matching head block root: {head_event_block_root}"
            )
            return (
                await self._produce_attestation_data_without_expected_head_block_root(
                    slot=slot
                )
            )
        else:
            self.logger.debug(
                "AttestationData received, confirming finality checkpoints"
            )

        # We have a full AttestationData object at this point. The only thing left is
        # to confirm the finality checkpoints. This part also has a timeout to make sure
        # we still at least have a chance to attest on time if we're unable to confirm
        # the checkpoints from the AttestationData.
        try:
            await asyncio.wait_for(
                self._confirm_finality_checkpoints(
                    source=att_data.source,
                    target=att_data.target,
                    slot=slot,
                ),
                timeout=self._timeout_head_event_checkpoint_confirmation,
            )
        except TimeoutError:
            # Failed to confirm the checkpoints for the AttestationData we retrieved.
            # --> The head event we received may be for a buggy chain. We can still
            #     attempt to attest using the fallback mechanism - attesting
            #     without an expected head block root.
            self.logger.warning(
                f"Timed out confirming finality checkpoints {att_data.source=}, {att_data.target=}"
            )
            return (
                await self._produce_attestation_data_without_expected_head_block_root(
                    slot=slot
                )
            )
        else:
            return att_data

    def prune(self) -> None:
        # Only keep up to 3 most recent checkpoints in the checkpoint confirmation cache
        self.source_checkpoint_confirmation_cache = dict(
            sorted(
                self.source_checkpoint_confirmation_cache.items(),
                key=lambda item: int(item[0]),
                reverse=True,
            )[:3]
        )
        self.target_checkpoint_confirmation_cache = dict(
            sorted(
                self.target_checkpoint_confirmation_cache.items(),
                key=lambda item: int(item[0]),
                reverse=True,
            )[:3]
        )
