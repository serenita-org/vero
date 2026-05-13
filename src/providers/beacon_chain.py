"""Provides information about the beacon chain - current slot, epoch, fork, genesis and spec data."""

import asyncio
import logging
import time
from math import floor
from typing import TYPE_CHECKING, Any

from schemas import SchemaBeaconAPI, SchemaRemoteSigner
from spec._ascii import GLOAS as GLOAS_ASCII_ART
from spec.base import Genesis, SpecGloas, Version
from tasks import TaskManager

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


class BeaconChain:
    def __init__(
        self,
        spec: SpecGloas,
        genesis: Genesis,
        task_manager: TaskManager,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.task_manager = task_manager

        self.genesis_time = int(genesis.genesis_time)
        self.genesis_validators_root = genesis.genesis_validators_root.to_obj()

        # Store the spec values we need
        # (accessing the attributes of the remerkleable-based Spec object directly
        # wastes a noticeable amount of CPU)
        self.SLOTS_PER_EPOCH = int(spec.SLOTS_PER_EPOCH)
        self.SLOT_DURATION_MS = int(spec.SLOT_DURATION_MS)

        self.ELECTRA_FORK_EPOCH = int(spec.ELECTRA_FORK_EPOCH)
        self.ELECTRA_FORK_VERSION = spec.ELECTRA_FORK_VERSION
        self.ELECTRA_FORK = SchemaRemoteSigner.Fork(
            previous_version=spec.DENEB_FORK_VERSION.to_obj(),
            current_version=spec.ELECTRA_FORK_VERSION.to_obj(),
            epoch=str(self.ELECTRA_FORK_EPOCH),
        )
        self.FULU_FORK_EPOCH = int(spec.FULU_FORK_EPOCH)
        self.FULU_FORK_VERSION = spec.FULU_FORK_VERSION
        self.FULU_FORK = SchemaRemoteSigner.Fork(
            previous_version=spec.ELECTRA_FORK_VERSION.to_obj(),
            current_version=spec.FULU_FORK_VERSION.to_obj(),
            epoch=str(self.FULU_FORK_EPOCH),
        )
        self.GLOAS_FORK_EPOCH = int(spec.GLOAS_FORK_EPOCH)
        self.GLOAS_FORK_VERSION = spec.GLOAS_FORK_VERSION
        self.GLOAS_FORK = SchemaRemoteSigner.Fork(
            previous_version=spec.FULU_FORK_VERSION.to_obj(),
            current_version=spec.GLOAS_FORK_VERSION.to_obj(),
            epoch=str(self.GLOAS_FORK_EPOCH),
        )

        current_epoch = self.current_slot // self.SLOTS_PER_EPOCH
        if current_epoch >= self.GLOAS_FORK_EPOCH:
            self.current_fork_version = SchemaBeaconAPI.ForkVersion.GLOAS
        elif current_epoch >= self.FULU_FORK_EPOCH:
            self._log_fork_readiness()
            self.current_fork_version = SchemaBeaconAPI.ForkVersion.FULU
        elif current_epoch >= self.ELECTRA_FORK_EPOCH:
            self.current_fork_version = SchemaBeaconAPI.ForkVersion.ELECTRA
        else:
            raise NotImplementedError(f"Unsupported fork for epoch {current_epoch}")

        self.new_slot_handlers: list[
            Callable[[int, bool], Coroutine[Any, Any, None]]
        ] = []

    def get_fork(self, slot: int) -> SchemaRemoteSigner.Fork:
        slot_epoch = slot // self.SLOTS_PER_EPOCH

        if slot_epoch >= self.GLOAS_FORK_EPOCH:
            return self.GLOAS_FORK
        if slot_epoch >= self.FULU_FORK_EPOCH:
            return self.FULU_FORK
        if slot_epoch >= self.ELECTRA_FORK_EPOCH:
            return self.ELECTRA_FORK
        raise NotImplementedError(f"Unsupported fork for epoch {slot_epoch}")

    def get_fork_info(self, slot: int) -> SchemaRemoteSigner.ForkInfo:
        return SchemaRemoteSigner.ForkInfo(
            fork=self.get_fork(slot=slot),
            genesis_validators_root=self.genesis_validators_root,
        )

    def get_fork_version(self, slot: int) -> Version:
        slot_epoch = slot // self.SLOTS_PER_EPOCH

        if slot_epoch >= self.GLOAS_FORK_EPOCH:
            return self.GLOAS_FORK_VERSION
        if slot_epoch >= self.FULU_FORK_EPOCH:
            return self.FULU_FORK_VERSION
        if slot_epoch >= self.ELECTRA_FORK_EPOCH:
            return self.ELECTRA_FORK_VERSION
        raise NotImplementedError(f"Unsupported fork for epoch {slot_epoch}")

    def _log_fork_readiness(self) -> None:
        self.logger.info(f"Ready for Gloas at epoch {self.GLOAS_FORK_EPOCH}")

    def start_slot_ticker(self) -> None:
        self.task_manager.create_task(self.on_new_slot())

    def get_timestamp_for_slot(self, slot: int) -> float:
        return self.genesis_time + (slot * self.SLOT_DURATION_MS) / 1_000

    @property
    def current_slot(self) -> int:
        ms_elapsed = floor(1_000 * (time.time() - self.genesis_time))
        ms_elapsed = max(0, ms_elapsed)
        return ms_elapsed // self.SLOT_DURATION_MS

    async def _precise_wait_for_timestamp(self, timestamp: float) -> None:
        # A slightly more accurate version of asyncio.sleep()
        delay = timestamp - time.time()

        # asyncio.sleep can be off by up to 16ms (on Windows)
        await asyncio.sleep(delay - 0.016)

        while time.time() < timestamp:  # noqa: ASYNC110
            await asyncio.sleep(0)

    async def wait_for_next_slot(self) -> None:
        # A slightly more accurate version of asyncio.sleep()
        await self._precise_wait_for_timestamp(
            self.get_timestamp_for_slot(self.current_slot + 1)
        )

    async def wait_for_epoch(self, epoch: int) -> None:
        epoch_start_timestamp = self.get_timestamp_for_slot(
            slot=epoch * self.SLOTS_PER_EPOCH
        )
        await self._precise_wait_for_timestamp(epoch_start_timestamp)

    async def on_new_slot(self) -> None:
        _current_slot = self.current_slot  # Cache property value
        _current_epoch, slot_no_in_epoch = divmod(_current_slot, self.SLOTS_PER_EPOCH)
        _is_new_epoch = slot_no_in_epoch == 0
        if _is_new_epoch:
            self.logger.info(f"Epoch {_current_epoch}")
        self.logger.info(f"Slot {_current_slot}")

        if _is_new_epoch:
            if _current_epoch < self.GLOAS_FORK_EPOCH:
                self._log_fork_readiness()
            elif _current_epoch == self.GLOAS_FORK_EPOCH:
                self.current_fork_version = SchemaBeaconAPI.ForkVersion.GLOAS
                self.logger.info(f"Gloas fork epoch reached! {GLOAS_ASCII_ART}")

        for handler in self.new_slot_handlers:
            self.task_manager.create_task(handler(_current_slot, _is_new_epoch))

        await self.wait_for_next_slot()
        self.task_manager.create_task(self.on_new_slot())

    def time_since_slot_start(self, slot: int) -> float:
        return time.time() - self.get_timestamp_for_slot(slot)

    @property
    def current_epoch(self) -> int:
        return self.current_slot // self.SLOTS_PER_EPOCH

    def compute_start_slot_at_epoch(self, epoch: int) -> int:
        return epoch * self.SLOTS_PER_EPOCH
