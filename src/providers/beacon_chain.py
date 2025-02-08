"""Provides information about the beacon chain - current slot, epoch, fork, genesis and spec data."""

import asyncio
import datetime
import logging
from math import floor
from typing import TYPE_CHECKING, Any

from schemas import SchemaBeaconAPI, SchemaRemoteSigner
from spec._ascii import ELECTRA as ELECTRA_ASCII_ART
from spec.base import Fork, Genesis, Spec
from tasks import TaskManager

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


class BeaconChain:
    def __init__(
        self,
        spec: Spec,
        task_manager: TaskManager,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.getLogger().level)

        self.spec = spec
        self.task_manager = task_manager

        self.genesis = Genesis()
        self.current_fork_version = SchemaBeaconAPI.ForkVersion.DENEB

        self.new_slot_handlers: list[
            Callable[[int, bool], Coroutine[Any, Any, None]]
        ] = []

    def get_fork(self, slot: int) -> Fork:
        slot_epoch = slot // self.spec.SLOTS_PER_EPOCH

        if slot_epoch >= self.spec.ELECTRA_FORK_EPOCH:
            return Fork(
                previous_version=self.spec.DENEB_FORK_VERSION,
                current_version=self.spec.ELECTRA_FORK_VERSION,
                epoch=self.spec.ELECTRA_FORK_EPOCH,
            )
        if slot_epoch >= self.spec.DENEB_FORK_EPOCH:
            return Fork(
                previous_version=self.spec.CAPELLA_FORK_VERSION,
                current_version=self.spec.DENEB_FORK_VERSION,
                epoch=self.spec.DENEB_FORK_EPOCH,
            )
        raise NotImplementedError(f"Unsupported fork for epoch {self.current_epoch}")

    def get_fork_info(self, slot: int) -> SchemaRemoteSigner.ForkInfo:
        return SchemaRemoteSigner.ForkInfo(
            fork=self.get_fork(slot=slot).to_obj(),
            genesis_validators_root=self.genesis.genesis_validators_root.to_obj(),
        )

    def initialize(self, genesis: Genesis) -> None:
        self.genesis = genesis

        current_epoch = self.current_slot // self.spec.SLOTS_PER_EPOCH
        if current_epoch >= self.spec.ELECTRA_FORK_EPOCH:
            self.current_fork_version = SchemaBeaconAPI.ForkVersion.ELECTRA
        else:
            self.current_fork_version = SchemaBeaconAPI.ForkVersion.DENEB

    def start_slot_ticker(self) -> None:
        self.task_manager.submit_task(self.on_new_slot())

    def get_datetime_for_slot(self, slot: int) -> datetime.datetime:
        slot_timestamp = self.genesis.genesis_time + slot * self.spec.SECONDS_PER_SLOT
        return datetime.datetime.fromtimestamp(slot_timestamp, tz=datetime.UTC)

    def _get_slots_since_genesis(self) -> int:
        seconds_elapsed = floor(
            datetime.datetime.now(tz=datetime.UTC).timestamp()
        ) - int(self.genesis.genesis_time)
        seconds_elapsed = max(0, seconds_elapsed)
        return seconds_elapsed // int(self.spec.SECONDS_PER_SLOT)

    @property
    def current_slot(self) -> int:
        return self._get_slots_since_genesis()

    async def wait_for_next_slot(self) -> None:
        # A slightly more accurate version of asyncio.sleep()
        _next_slot = self.current_slot + 1
        _delay = (
            self.get_datetime_for_slot(_next_slot)
            - datetime.datetime.now(tz=datetime.UTC)
        ).total_seconds()

        # asyncio.sleep can be off by up to 16ms (on Windows)
        await asyncio.sleep(_delay - 0.016)

        while self.current_slot < _next_slot:  # noqa: ASYNC110
            await asyncio.sleep(0)

    async def on_new_slot(self) -> None:
        _current_slot = self.current_slot  # Cache property value
        self.logger.info(f"Slot {_current_slot}")
        _is_new_epoch = _current_slot % self.spec.SLOTS_PER_EPOCH == 0

        if _is_new_epoch:
            _current_epoch = _current_slot // self.spec.SLOTS_PER_EPOCH
            if _current_epoch == self.spec.ELECTRA_FORK_EPOCH:
                self.current_fork_version = SchemaBeaconAPI.ForkVersion.ELECTRA
                self.logger.info(f"Electra fork epoch reached! {ELECTRA_ASCII_ART}")

        for handler in self.new_slot_handlers:
            self.task_manager.submit_task(handler(_current_slot, _is_new_epoch))

        await self.wait_for_next_slot()
        self.task_manager.submit_task(self.on_new_slot())

    def time_since_slot_start(self, slot: int) -> float:
        return (
            datetime.datetime.now(tz=datetime.UTC) - self.get_datetime_for_slot(slot)
        ).total_seconds()

    @property
    def current_epoch(self) -> int:
        return self.current_slot // self.spec.SLOTS_PER_EPOCH  # type: ignore[no-any-return]

    def compute_start_slot_at_epoch(self, epoch: int) -> int:
        return epoch * self.spec.SLOTS_PER_EPOCH  # type: ignore[no-any-return]

    def compute_epochs_for_sync_period(self, sync_period: int) -> tuple[int, int]:
        start_epoch = sync_period * self.spec.EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        end_epoch = start_epoch + self.spec.EPOCHS_PER_SYNC_COMMITTEE_PERIOD
        return start_epoch, end_epoch

    def compute_sync_period_for_epoch(self, epoch: int) -> int:
        return epoch // self.spec.EPOCHS_PER_SYNC_COMMITTEE_PERIOD  # type: ignore[no-any-return]

    def compute_sync_period_for_slot(self, slot: int) -> int:
        return self.compute_sync_period_for_epoch(
            epoch=slot // self.spec.SLOTS_PER_EPOCH,
        )
