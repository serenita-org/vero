import asyncio
import logging
import time
from typing import TYPE_CHECKING

from providers import BeaconChain, BeaconNode

if TYPE_CHECKING:
    from services import ValidatorStatusTrackerService


class DoppelgangersDetected(Exception):
    pass


class DoppelgangerDetector:
    def __init__(
        self,
        beacon_chain: BeaconChain,
        beacon_nodes: list[BeaconNode],
        validator_status_tracker_service: "ValidatorStatusTrackerService",
    ):
        self.logger = logging.getLogger(self.__class__.__name__)

        self.beacon_chain = beacon_chain
        self.beacon_nodes = beacon_nodes
        self.validator_status_tracker_service = validator_status_tracker_service

    async def _fetch_liveness_data(
        self, epoch: int, validator_indices: list[int]
    ) -> set[int]:
        results = await asyncio.gather(
            *[
                beacon_node.get_liveness(
                    epoch=epoch,
                    validator_indices=validator_indices,
                )
                for beacon_node in self.beacon_nodes
            ],
            return_exceptions=True,
        )

        live_indices: set[int] = set()
        for result in results:
            if isinstance(result, BaseException):
                self.logger.error(
                    f"Failed to query beacon node for liveness data for epoch {epoch}"
                    f" - did you enable liveness tracking?"
                    f"\n{result!r}"
                )
                raise result

            bn_host, liveness_data = result
            self.logger.debug(
                f"Liveness response from {bn_host}: {liveness_data}",
            )
            live_indices.update([int(v.index) for v in liveness_data if v.is_live])

        return live_indices

    def _process_liveness_data(self, live_indices: set[int]) -> None:
        if live_indices:
            self.logger.critical(
                f"Doppelgangers detected by beacon nodes: {live_indices}"
            )
            raise DoppelgangersDetected

        self.logger.debug("No doppelgangers detected across beacon nodes")

    async def _raise_if_doppelganger_detected(
        self, epoch: int, validator_indices: list[int]
    ) -> None:
        self._process_liveness_data(
            await self._fetch_liveness_data(
                epoch=epoch,
                validator_indices=validator_indices,
            )
        )

    async def detect(self) -> None:
        validator_indices = (
            self.validator_status_tracker_service.active_or_pending_indices
        )
        self.logger.info(
            f"Attempting to detect doppelgangers for {len(validator_indices)} validators"
        )

        # Query the beacon node right away just to check early on that querying the
        # liveness endpoint works (it needs to be explicitly enabled for some CL clients)
        current_epoch = self.beacon_chain.current_epoch
        await self._fetch_liveness_data(
            epoch=current_epoch,
            validator_indices=validator_indices,
        )

        epoch_to_monitor_for_attestations = current_epoch + 1
        self.logger.info(
            f"Waiting for monitored epoch {epoch_to_monitor_for_attestations} to start"
        )
        await self.beacon_chain.wait_for_epoch(epoch_to_monitor_for_attestations)

        self.logger.info(
            f"Waiting for monitored epoch {epoch_to_monitor_for_attestations} to finish"
        )
        await self.beacon_chain.wait_for_epoch(epoch_to_monitor_for_attestations + 1)

        # Check the liveness data when the monitored epoch ends.
        # If there is an active doppelganger, there's a good chance we
        # can detect it already.
        await self._raise_if_doppelganger_detected(
            epoch=epoch_to_monitor_for_attestations,
            validator_indices=validator_indices,
        )
        self.logger.info(
            f"Attestations made during epoch {epoch_to_monitor_for_attestations} may be"
            f" included in the next epoch too."
        )

        # Attestations made during the `epoch_to_monitor_for_attestations` can be included
        # in the next epoch too...
        # With EIP-7045, attestations from any slot in epoch N can be included in the
        # very last slot of epoch N+1 so we should check once we have seen the last block
        # in epoch N+1.
        # Therefore, wait for the next epoch to almost finish as well, waiting
        # until we're halfway into the last slot of the next epoch.
        last_slot_in_next_epoch = (
            (epoch_to_monitor_for_attestations + 2) * self.beacon_chain.SLOTS_PER_EPOCH
        ) - 1
        ts_to_wait_for = self.beacon_chain.get_timestamp_for_slot(
            slot=last_slot_in_next_epoch,
        ) + (self.beacon_chain.SECONDS_PER_SLOT / 2)
        self.logger.info(
            "Waiting for last slot in epoch "
            f"{epoch_to_monitor_for_attestations + 1}: {last_slot_in_next_epoch}"
        )
        await asyncio.sleep(ts_to_wait_for - time.time())

        # Check the latest liveness data one more time. If the function doesn't raise,
        # we didn't detect any doppelgangers. This `detect()` function will return
        # without raising and Vero can start performing duties.
        await self._raise_if_doppelganger_detected(
            epoch=epoch_to_monitor_for_attestations,
            validator_indices=validator_indices,
        )
        self.logger.info("No doppelgangers detected!")
