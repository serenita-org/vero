import logging
from pathlib import Path
from typing import Annotated

import msgspec

from schemas import SchemaBeaconAPI

DutyDependentRoot = Annotated[str, msgspec.Meta(pattern="^0x[a-fA-F0-9]{64}$")]
Epoch = Annotated[int, msgspec.Meta()]


def _load_bytes_from_fp(fp: Path) -> bytes:
    with Path.open(fp, "rb") as f:
        return f.read()


def _save_bytes_to_fp(bytes_: bytes, fp: Path) -> None:
    with Path.open(fp, "wb") as f:
        f.write(bytes_)


class DutyCache:
    attester_duties_fname = "cache_attester_duties.json"
    attester_dep_roots_fname = "cache_attester_dependent_roots.json"
    proposer_duties_fname = "cache_proposer_duties.json"
    proposer_dep_roots_fname = "cache_proposer_dependent_roots.json"
    sync_duties_fname = "cache_sync_duties.json"

    def __init__(self, data_dir: str) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.data_dir = Path(data_dir)
        self.json_encoder = msgspec.json.Encoder()

    def load_attester_duties(
        self,
    ) -> tuple[
        dict[Epoch, set[SchemaBeaconAPI.AttesterDutyWithSelectionProof]],
        dict[Epoch, DutyDependentRoot],
    ]:
        duties = msgspec.json.decode(
            _load_bytes_from_fp(self.data_dir / self.attester_duties_fname),
            type=dict[Epoch, set[SchemaBeaconAPI.AttesterDutyWithSelectionProof]],
        )
        dependent_roots = msgspec.json.decode(
            _load_bytes_from_fp(self.data_dir / self.attester_dep_roots_fname),
            type=dict[Epoch, DutyDependentRoot],
        )
        return duties, dependent_roots

    def cache_attester_duties(
        self,
        duties: dict[Epoch, set[SchemaBeaconAPI.AttesterDutyWithSelectionProof]],
        dependent_roots: dict[Epoch, DutyDependentRoot],
    ) -> None:
        _save_bytes_to_fp(
            bytes_=self.json_encoder.encode(duties),
            fp=self.data_dir / self.attester_duties_fname,
        )
        _save_bytes_to_fp(
            bytes_=self.json_encoder.encode(dependent_roots),
            fp=self.data_dir / self.attester_dep_roots_fname,
        )

    def load_proposer_duties(
        self,
    ) -> tuple[
        dict[Epoch, set[SchemaBeaconAPI.ProposerDuty]],
        dict[Epoch, DutyDependentRoot],
    ]:
        duties = msgspec.json.decode(
            _load_bytes_from_fp(self.data_dir / self.proposer_duties_fname),
            type=dict[Epoch, set[SchemaBeaconAPI.ProposerDuty]],
        )
        dependent_roots = msgspec.json.decode(
            _load_bytes_from_fp(self.data_dir / self.proposer_dep_roots_fname),
            type=dict[Epoch, DutyDependentRoot],
        )
        return duties, dependent_roots

    def cache_proposer_duties(
        self,
        duties: dict[Epoch, set[SchemaBeaconAPI.ProposerDuty]],
        dependent_roots: dict[Epoch, DutyDependentRoot],
    ) -> None:
        _save_bytes_to_fp(
            bytes_=self.json_encoder.encode(duties),
            fp=self.data_dir / self.proposer_duties_fname,
        )
        _save_bytes_to_fp(
            bytes_=self.json_encoder.encode(dependent_roots),
            fp=self.data_dir / self.proposer_dep_roots_fname,
        )

    def load_sync_duties(self) -> dict[Epoch, list[SchemaBeaconAPI.SyncDuty]]:
        return msgspec.json.decode(
            _load_bytes_from_fp(self.data_dir / self.sync_duties_fname),
            type=dict[Epoch, list[SchemaBeaconAPI.SyncDuty]],
        )

    def cache_sync_duties(
        self,
        duties: dict[Epoch, list[SchemaBeaconAPI.SyncDuty]],
    ) -> None:
        _save_bytes_to_fp(
            bytes_=self.json_encoder.encode(duties),
            fp=self.data_dir / self.sync_duties_fname,
        )
