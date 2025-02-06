import datetime
import os
import random
import re
from typing import Any

import msgspec
import pytest
from aioresponses import CallbackResult, aioresponses
from remerkleable.bitfields import Bitlist, Bitvector
from yarl import URL

from providers import BeaconChain
from schemas import SchemaBeaconAPI
from schemas.beacon_api import ForkVersion
from schemas.validator import ValidatorIndexPubkey
from spec import SpecAttestation, SpecBeaconBlock, SpecSyncCommittee
from spec.attestation import AttestationData, Checkpoint
from spec.base import Fork, Genesis, SpecElectra
from spec.constants import (
    TARGET_AGGREGATORS_PER_COMMITTEE,
    TARGET_AGGREGATORS_PER_SYNC_SUBCOMMITTEE,
)


@pytest.fixture(scope="session")
def beacon_node_url() -> str:
    return "http://beacon-node-1:1234"


@pytest.fixture
def execution_payload_blinded(request: pytest.FixtureRequest) -> bool:
    return getattr(request, "param", False)


@pytest.fixture(scope="session")
def mocked_fork_response() -> dict:  # type: ignore[type-arg]
    return dict(
        data=Fork.from_obj(
            dict(
                previous_version="0x04017000",
                current_version="0x05017000",
                epoch=3,
            ),
        ).to_obj(),
    )


@pytest.fixture(scope="session")
def mocked_genesis_response() -> dict:  # type: ignore[type-arg]
    return dict(
        data=Genesis.from_obj(
            dict(
                genesis_time=int(
                    (
                        datetime.datetime.now(tz=datetime.UTC)
                        - datetime.timedelta(days=30)
                    ).timestamp()
                ),
                genesis_validators_root="0x9143aa7c615a7f7115e2b6aac319c03529df8242ae705fba9df39b79c59fa8b1",
                genesis_fork_version="0x10000038",
            ),
        ).to_obj(),
    )


@pytest.fixture
def _mocked_beacon_node_endpoints(
    validators: list[ValidatorIndexPubkey],
    spec: SpecElectra,
    beacon_chain: BeaconChain,
    mocked_fork_response: dict,  # type: ignore[type-arg]
    mocked_genesis_response: dict,  # type: ignore[type-arg]
    mocked_responses: aioresponses,
    execution_payload_blinded: bool,
) -> None:
    def _mocked_beacon_api_endpoints_get(url: URL, **kwargs: Any) -> CallbackResult:
        if re.match(r"/eth/v1/beacon/states/\w+/fork", url.raw_path):
            return CallbackResult(payload=mocked_fork_response)

        if re.match("/eth/v1/beacon/genesis", url.raw_path):
            return CallbackResult(payload=mocked_genesis_response)

        if re.match("/eth/v1/config/spec", url.raw_path):
            return CallbackResult(payload=dict(data=spec.to_obj()))

        if re.match("/eth/v1/node/version", url.raw_path):
            return CallbackResult(payload=dict(data=dict(version="vero/test")))

        if re.match(r"/eth/v1/validator/duties/proposer/\d+", url.raw_path):
            epoch_no = int(url.raw_path.split("/")[-1])

            return CallbackResult(
                body=msgspec.json.encode(
                    SchemaBeaconAPI.GetProposerDutiesResponse(
                        dependent_root="0xab09edd9380f8451c3ff5c809821174a36dce606fea8b5ea35ea936915dbf889",
                        execution_optimistic=False,
                        data=[
                            SchemaBeaconAPI.ProposerDuty(
                                pubkey="0x" + os.urandom(48).hex(),
                                validator_index=str(random.randint(0, 1_000_000)),
                                slot=str(epoch_no * spec.SLOTS_PER_EPOCH + slot_no),
                            )
                            for slot_no in range(spec.SLOTS_PER_EPOCH)
                        ],
                    )
                ),
            )

        if re.match("/eth/v3/validator/blocks/.*", url.raw_path):
            slot = int(url.raw_path.split("/")[-1])

            if beacon_chain.current_fork_version == ForkVersion.ELECTRA:
                fork_version = SchemaBeaconAPI.ForkVersion.ELECTRA
                if execution_payload_blinded:
                    _data = SpecBeaconBlock.ElectraBlinded(
                        slot=slot,
                        proposer_index=123,
                        parent_root="0xcbe950dda3533e3c257fd162b33d791f9073eb42e4da21def569451e9323c33e",
                        state_root="0xd9f5a83718a7657f50bc3c5be8c2b2fd7f051f44d2962efdde1e30cee881e7f6",
                        # body=...
                    ).to_obj()
                else:
                    _data = dict(
                        block=SpecBeaconBlock.Electra(
                            slot=slot,
                            proposer_index=123,
                            parent_root="0xcbe950dda3533e3c257fd162b33d791f9073eb42e4da21def569451e9323c33e",
                            state_root="0xd9f5a83718a7657f50bc3c5be8c2b2fd7f051f44d2962efdde1e30cee881e7f6",
                            # body=...
                        ).to_obj(),
                    )
            elif beacon_chain.current_fork_version == ForkVersion.DENEB:
                fork_version = SchemaBeaconAPI.ForkVersion.DENEB
                if execution_payload_blinded:
                    _data = SpecBeaconBlock.DenebBlinded(
                        slot=slot,
                        proposer_index=123,
                        parent_root="0xcbe950dda3533e3c257fd162b33d791f9073eb42e4da21def569451e9323c33e",
                        state_root="0xd9f5a83718a7657f50bc3c5be8c2b2fd7f051f44d2962efdde1e30cee881e7f6",
                        # body=...
                    ).to_obj()
                else:
                    _data = dict(
                        block=SpecBeaconBlock.Deneb(
                            slot=slot,
                            proposer_index=123,
                            parent_root="0xcbe950dda3533e3c257fd162b33d791f9073eb42e4da21def569451e9323c33e",
                            state_root="0xd9f5a83718a7657f50bc3c5be8c2b2fd7f051f44d2962efdde1e30cee881e7f6",
                            # body=...
                        ).to_obj(),
                    )
            else:
                raise NotImplementedError(f"Endpoint not implemented for spec {spec}")

            return CallbackResult(
                body=msgspec.json.encode(
                    SchemaBeaconAPI.ProduceBlockV3Response(
                        version=fork_version,
                        execution_payload_blinded=execution_payload_blinded,
                        execution_payload_value=str(random.randint(0, 10_000_000)),
                        consensus_block_value=str(random.randint(0, 10_000_000)),
                        data=_data,
                    )
                )
            )

        if re.match("/eth/v1/validator/attestation_data", url.raw_path):
            att_data = AttestationData(
                slot=int(url.query["slot"]),
                index=int(url.query["committee_index"]),
                beacon_block_root="0x9f19cc6499596bdf19be76d80b878ee3326e68cf2ed69cbada9a1f4fe13c51b3",
            )
            return CallbackResult(payload=dict(data=att_data.to_obj()))

        if re.match("/eth/v2/validator/aggregate_attestation", url.raw_path):
            if beacon_chain.current_fork_version == ForkVersion.ELECTRA:
                fork_version = SchemaBeaconAPI.ForkVersion.ELECTRA

                _committee_bits = Bitvector[spec.MAX_COMMITTEES_PER_SLOT](
                    False for _ in range(spec.MAX_COMMITTEES_PER_SLOT)
                )
                _committee_bits[int(url.query["committee_index"])] = True
                _agg_bitlist_size = (
                    spec.MAX_VALIDATORS_PER_COMMITTEE * spec.MAX_COMMITTEES_PER_SLOT
                )
                _agg_bits = [1, 0, 1, 0, 1, 1, 1, 0, 1, 1] + [
                    1 for _ in range(_agg_bitlist_size - 10)
                ]
                aggregate_attestation = SpecAttestation.AttestationElectra(
                    aggregation_bits=Bitlist[_agg_bitlist_size](_agg_bits),
                    data=AttestationData(
                        slot=int(url.query["slot"]),
                        index=0,
                        beacon_block_root="0x9f19cc6499596bdf19be76d80b878ee3326e68cf2ed69cbada9a1f4fe13c51b3",
                        source=Checkpoint(
                            epoch=5,
                            root="0xfd87176458a22999a87872fc9cbbba38bdeeb37847091875fb4ff82dd3d05abf",
                        ),
                        target=Checkpoint(
                            epoch=6,
                            root="0x62e8fb27f17e5fb962503a56f07d14b5bf8710fb6b53bc9ef78f04c82d46a460",
                        ),
                    ),
                    signature="0x4992b42d8d9b7827accbc94523fb1f98f866bd53105155907179238e00dfec8ab4618de8ff0361c818e5703a191ad16beedeff4c4341ac3fe3c935e01ffbc2199b7212d371f0dcf5bd2db993c51d9554609235a4a86d1f0e85074d014f8e494b",
                    committee_bits=_committee_bits,
                )
            elif beacon_chain.current_fork_version == ForkVersion.DENEB:
                fork_version = SchemaBeaconAPI.ForkVersion.DENEB
                # Deterministic return data to make it possible to
                # check the submitted aggregate in the other endpoint
                _agg_bitlist_size = spec.MAX_VALIDATORS_PER_COMMITTEE
                _agg_bits = [1, 0, 1, 0, 1, 1, 1, 0, 1, 1] + [
                    1 for _ in range(_agg_bitlist_size - 10)
                ]
                aggregate_attestation = SpecAttestation.AttestationPhase0(
                    aggregation_bits=Bitlist[spec.MAX_VALIDATORS_PER_COMMITTEE](
                        _agg_bits
                    ),
                    data=AttestationData(
                        slot=int(url.query["slot"]),
                        index=int(url.query["committee_index"]),
                        beacon_block_root="0x9f19cc6499596bdf19be76d80b878ee3326e68cf2ed69cbada9a1f4fe13c51b3",
                        source=Checkpoint(
                            epoch=2,
                            root="0x6ec25dbfa49e671629fdc437beb2acf02d16763ef05bdeb6351d9ead027b24b4",
                        ),
                        target=Checkpoint(
                            epoch=3,
                            root="0x3b3ee1a4cf6c952285e8f2114573b0526968766370761bfa6a09705028cbe62a",
                        ),
                    ),
                    signature="0x582e78b397101fa0a611a278296ad4752e46a4d573fc0fe57092ffa2ad5dcd5bdcc3ea94c98958aeba4fb09b4e2ce07ee02f54f50234575e3ca250855f57d088c5b61bd3a99571f522b6997aed5844fcab841e820e428e7cfd5794d6f0efdce1",
                )
            else:
                raise ValueError(f"Unsupported spec: {spec}")

            return CallbackResult(
                body=msgspec.json.encode(
                    SchemaBeaconAPI.GetAggregatedAttestationV2Response(
                        version=fork_version,
                        data=aggregate_attestation.to_obj(),
                    )
                )
            )

        if re.match("/eth/v1/beacon/blocks/head/root", url.raw_path):
            return CallbackResult(
                body=msgspec.json.encode(
                    SchemaBeaconAPI.GetBlockRootResponse(
                        execution_optimistic=False,
                        data=SchemaBeaconAPI.BlockRoot(
                            root="0x" + os.urandom(32).hex()
                        ),
                    )
                )
            )

        if re.match("/eth/v1/validator/sync_committee_contribution", url.raw_path):
            contribution = SpecSyncCommittee.Contribution(
                slot=int(url.query["slot"]),
                beacon_block_root=url.query["beacon_block_root"],
                subcommittee_index=int(url.query["subcommittee_index"]),
                aggregation_bits=Bitlist[TARGET_AGGREGATORS_PER_SYNC_SUBCOMMITTEE](
                    random.choice([0, 1])
                    for _ in range(TARGET_AGGREGATORS_PER_SYNC_SUBCOMMITTEE)
                ),
                signature="0x" + os.urandom(96).hex(),
            )

            return CallbackResult(payload=dict(data=contribution.to_obj()))

        raise NotImplementedError(
            f"Beacon API response for GET {url} does not have a mock handler",
        )

    def _mocked_beacon_api_endpoints_post(url: URL, **kwargs: Any) -> CallbackResult:
        if re.match(r"/eth/v1/beacon/states/\w*/validators", url.raw_path):
            data = msgspec.json.decode(kwargs["data"])
            ids = data["ids"]
            statuses = data["statuses"]

            return CallbackResult(
                body=msgspec.json.encode(
                    SchemaBeaconAPI.GetStateValidatorsResponse(
                        execution_optimistic=False,
                        data=[
                            SchemaBeaconAPI.ValidatorInfo(
                                index=str(validator.index),
                                status=validator.status,
                                validator=SchemaBeaconAPI.Validator(
                                    pubkey=validator.pubkey
                                ),
                            )
                            for validator in validators
                            if validator.status.value in statuses
                            and validator.pubkey in ids
                        ],
                    )
                )
            )

        if re.match("/eth/v1/validator/prepare_beacon_proposer", url.raw_path):
            return CallbackResult(status=200)

        if re.match("/eth/v1/validator/register_validator", url.raw_path):
            return CallbackResult(status=200)

        if re.match("/eth/v2/beacon/blocks", url.raw_path):
            return CallbackResult(status=200)

        if re.match("/eth/v2/beacon/blinded_blocks", url.raw_path):
            return CallbackResult(status=200)

        if re.match(r"/eth/v1/validator/duties/attester/\d+", url.raw_path):
            epoch_no = int(url.raw_path.split("/")[-1])

            # This endpoint returns only duties for the validators
            # specified in the response
            attester_duties = []
            for v in validators:
                duty_slot = epoch_no * spec.SLOTS_PER_EPOCH + random.randint(
                    0,
                    spec.SLOTS_PER_EPOCH,
                )
                attester_duties.append(
                    SchemaBeaconAPI.AttesterDuty(
                        pubkey=v.pubkey,
                        validator_index=str(v.index),
                        committee_index=str(
                            random.randint(
                                0,
                                TARGET_AGGREGATORS_PER_COMMITTEE,
                            )
                        ),
                        committee_length=str(TARGET_AGGREGATORS_PER_COMMITTEE),
                        committees_at_slot=str(random.randint(0, 10)),
                        validator_committee_index=str(
                            random.randint(
                                0,
                                TARGET_AGGREGATORS_PER_COMMITTEE,
                            )
                        ),
                        slot=str(duty_slot),
                    ),
                )

            return CallbackResult(
                body=msgspec.json.encode(
                    SchemaBeaconAPI.GetAttesterDutiesResponse(
                        dependent_root="0xab09edd9380f8451c3ff5c809821174a36dce606fea8b5ea35ea936915dbf889",
                        execution_optimistic=False,
                        data=attester_duties,
                    )
                )
            )

        if re.match("/eth/v1/validator/beacon_committee_subscriptions", url.raw_path):
            return CallbackResult(status=200)

        if re.match("/eth/v2/beacon/pool/attestations", url.raw_path):
            data_list = msgspec.json.decode(kwargs["data"])
            assert len(data_list) == 1
            data = data_list[0]
            assert (
                data["data"]["beacon_block_root"]
                == "0x9f19cc6499596bdf19be76d80b878ee3326e68cf2ed69cbada9a1f4fe13c51b3"
            )

            if beacon_chain.current_fork_version == ForkVersion.ELECTRA:
                assert "committee_index" in data
                assert "attester_index" in data
            elif beacon_chain.current_fork_version == ForkVersion.DENEB:
                assert data["aggregation_bits"] == "0x000201"
                assert "committee_bits" not in data
            else:
                raise ValueError(f"Unsupported spec: {spec}")

            return CallbackResult(status=200)

        if re.match("/eth/v2/validator/aggregate_and_proofs", url.raw_path):
            data_list = msgspec.json.decode(kwargs["data"])
            assert len(data_list) == 1
            data = data_list[0]

            assert data["message"]["aggregator_index"] == "1"
            aggregate = data["message"]["aggregate"]

            if beacon_chain.current_fork_version == ForkVersion.ELECTRA:
                assert aggregate["committee_bits"] == "0x0040000000000000"
                assert aggregate["aggregation_bits"] == f"0x75{32766 * 'f'}01"
            elif beacon_chain.current_fork_version == ForkVersion.DENEB:
                assert aggregate["data"]["index"] == "14"
                assert aggregate["aggregation_bits"] == f"0x75{510 * 'f'}01"
            else:
                raise ValueError(f"Unsupported spec: {spec}")
            return CallbackResult(status=200)

        if re.match(r"/eth/v1/validator/duties/sync/\d+", url.raw_path):
            epoch_no = int(url.raw_path.split("/")[-1])

            # This endpoint returns only duties for the validators
            # specified in the response
            sync_duties = [
                SchemaBeaconAPI.SyncDuty(
                    pubkey=v.pubkey,
                    validator_index=str(v.index),
                    validator_sync_committee_indices=[],
                )
                for v in validators
            ]

            return CallbackResult(
                body=msgspec.json.encode(
                    SchemaBeaconAPI.GetSyncDutiesResponse(
                        execution_optimistic=False,
                        data=sync_duties,
                    )
                )
            )

        if re.match("/eth/v1/validator/sync_committee_subscriptions", url.raw_path):
            return CallbackResult(status=200)

        if re.match("/eth/v1/beacon/pool/sync_committees", url.raw_path):
            return CallbackResult(status=200)

        if re.match("/eth/v1/validator/contribution_and_proofs", url.raw_path):
            return CallbackResult(status=200)

        raise NotImplementedError(
            f"Beacon API response for POST {url} does not have a mock handler",
        )

    mocked_responses.get(
        url=re.compile(r"http://beacon-node-[\w\-]+:1234/eth/"),
        callback=_mocked_beacon_api_endpoints_get,
        repeat=True,
    )
    mocked_responses.post(
        url=re.compile(r"http://beacon-node-[\w\-]+:1234/eth/"),
        callback=_mocked_beacon_api_endpoints_post,
        repeat=True,
    )
