"""Provides information about the beacon chain - current slot, epoch, fork, genesis and spec data."""

import asyncio
import logging
import time
from math import floor
from typing import TYPE_CHECKING, Any

from schemas import SchemaBeaconAPI, SchemaRemoteSigner
from spec._ascii import ELECTRA as ELECTRA_ASCII_ART
from spec.base import Genesis, SpecElectra
from tasks import TaskManager

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


class BeaconChain:
    def __init__(
        self,
        spec: SpecElectra,
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
        self.SECONDS_PER_SLOT = int(spec.SECONDS_PER_SLOT)
        self.EPOCHS_PER_SYNC_COMMITTEE_PERIOD = int(
            spec.EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        )
        self.MAX_VALIDATORS_PER_COMMITTEE = int(spec.MAX_VALIDATORS_PER_COMMITTEE)
        self.MAX_COMMITTEES_PER_SLOT = int(spec.MAX_COMMITTEES_PER_SLOT)
        self.SYNC_COMMITTEE_SIZE = int(spec.SYNC_COMMITTEE_SIZE)

        self.CAPELLA_FORK_VERSION = spec.CAPELLA_FORK_VERSION.to_obj()
        self.DENEB_FORK_EPOCH = spec.DENEB_FORK_EPOCH.to_obj()
        self.DENEB_FORK_VERSION = spec.DENEB_FORK_VERSION.to_obj()
        self.ELECTRA_FORK_EPOCH = spec.ELECTRA_FORK_EPOCH.to_obj()
        self.ELECTRA_FORK_VERSION = spec.DENEB_FORK_VERSION.to_obj()

        current_epoch = self.current_slot // self.SLOTS_PER_EPOCH
        if current_epoch >= self.ELECTRA_FORK_EPOCH:
            self.current_fork_version = SchemaBeaconAPI.ForkVersion.ELECTRA
        else:
            self._log_fork_readiness()
            self.current_fork_version = SchemaBeaconAPI.ForkVersion.DENEB

        self.new_slot_handlers: list[
            Callable[[int, bool], Coroutine[Any, Any, None]]
        ] = []

    def get_fork(self, slot: int) -> SchemaRemoteSigner.Fork:
        slot_epoch = slot // self.SLOTS_PER_EPOCH

        if slot_epoch >= self.ELECTRA_FORK_EPOCH:
            return SchemaRemoteSigner.Fork(
                previous_version=self.DENEB_FORK_VERSION,
                current_version=self.ELECTRA_FORK_VERSION,
                epoch=str(self.ELECTRA_FORK_EPOCH),
            )
        if slot_epoch >= self.DENEB_FORK_EPOCH:
            return SchemaRemoteSigner.Fork(
                previous_version=self.CAPELLA_FORK_VERSION,
                current_version=self.DENEB_FORK_VERSION,
                epoch=str(self.DENEB_FORK_EPOCH),
            )
        raise NotImplementedError(f"Unsupported fork for epoch {self.current_epoch}")

    def get_fork_info(self, slot: int) -> SchemaRemoteSigner.ForkInfo:
        return SchemaRemoteSigner.ForkInfo(
            fork=self.get_fork(slot=slot),
            genesis_validators_root=self.genesis_validators_root,
        )

    def _log_fork_readiness(self) -> None:
        self.logger.info(f"Ready for Electra at epoch {self.ELECTRA_FORK_EPOCH}")

    def start_slot_ticker(self) -> None:
        self.task_manager.submit_task(self.on_new_slot())

    def get_timestamp_for_slot(self, slot: int) -> int:
        return self.genesis_time + slot * self.SECONDS_PER_SLOT

    @property
    def current_slot(self) -> int:
        seconds_elapsed = floor(time.time()) - int(self.genesis.genesis_time)
        seconds_elapsed = max(0, seconds_elapsed)
        return seconds_elapsed // self.SECONDS_PER_SLOT

    async def wait_for_next_slot(self) -> None:
        # A slightly more accurate version of asyncio.sleep()
        _next_slot = self.current_slot + 1
        _delay = self.get_timestamp_for_slot(_next_slot) - time.time()

        # asyncio.sleep can be off by up to 16ms (on Windows)
        await asyncio.sleep(_delay - 0.016)

        while self.current_slot < _next_slot:  # noqa: ASYNC110
            await asyncio.sleep(0)

    async def on_new_slot(self) -> None:
        _current_slot = self.current_slot  # Cache property value
        _current_epoch, slot_no_in_epoch = divmod(_current_slot, self.SLOTS_PER_EPOCH)
        _is_new_epoch = slot_no_in_epoch == 0
        if _is_new_epoch:
            self.logger.info(f"Epoch {_current_epoch}")
        self.logger.info(f"Slot {_current_slot}")

        if _is_new_epoch:
            if _current_epoch < self.ELECTRA_FORK_EPOCH:
                self._log_fork_readiness()
            elif _current_epoch == self.ELECTRA_FORK_EPOCH:
                self.current_fork_version = SchemaBeaconAPI.ForkVersion.ELECTRA
                self.logger.info(f"Electra fork epoch reached! {ELECTRA_ASCII_ART}")

        for handler in self.new_slot_handlers:
            self.task_manager.submit_task(handler(_current_slot, _is_new_epoch))

        await self.wait_for_next_slot()
        self.task_manager.submit_task(self.on_new_slot())

    def time_since_slot_start(self, slot: int) -> float:
        return time.time() - self.get_timestamp_for_slot(slot)

    @property
    def current_epoch(self) -> int:
        return self.current_slot // self.SLOTS_PER_EPOCH

    def compute_start_slot_at_epoch(self, epoch: int) -> int:
        return epoch * self.SLOTS_PER_EPOCH

    def compute_epochs_for_sync_period(self, sync_period: int) -> tuple[int, int]:
        start_epoch = sync_period * self.EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        end_epoch = start_epoch + self.EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        return start_epoch, end_epoch

    def compute_sync_period_for_epoch(self, epoch: int) -> int:
        return epoch // self.EPOCHS_PER_SYNC_COMMITTEE_PERIOD

    def compute_sync_period_for_slot(self, slot: int) -> int:
        return self.compute_sync_period_for_epoch(
            epoch=slot // self.SLOTS_PER_EPOCH,
        )
