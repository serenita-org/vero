import os
import random
import re
from typing import Any

import msgspec
import pytest
from aioresponses import CallbackResult, aioresponses
from remerkleable.bitfields import Bitlist
from yarl import URL

from schemas import SchemaBeaconAPI
from schemas.validator import ValidatorIndexPubkey
from spec import SpecAttestation, SpecBeaconBlock, SpecSyncCommittee
from spec.attestation import AttestationData, Checkpoint
from spec.base import Fork, Genesis, SpecDeneb


@pytest.fixture(scope="session")
def beacon_node_url() -> str:
    return "http://beacon-node-1:1234"


@pytest.fixture
def execution_payload_blinded(request: pytest.FixtureRequest) -> bool:
    return getattr(request, "param", False)


@pytest.fixture
def _beacon_block_class_init(spec_deneb: SpecDeneb) -> None:
    SpecBeaconBlock.initialize(spec=spec_deneb)


@pytest.fixture
def _sync_committee_contribution_class_init(spec_deneb: SpecDeneb) -> None:
    SpecSyncCommittee.initialize(spec=spec_deneb)


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
                genesis_time=1695902100,
                genesis_validators_root="0x9143aa7c615a7f7115e2b6aac319c03529df8242ae705fba9df39b79c59fa8b1",
                genesis_fork_version="0x10000038",
            ),
        ).to_obj(),
    )


@pytest.fixture
def _mocked_beacon_node_endpoints(
    validators: list[ValidatorIndexPubkey],
    spec_deneb: SpecDeneb,
    _beacon_block_class_init: None,
    _sync_committee_contribution_class_init: None,
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
            return CallbackResult(payload=dict(data=spec_deneb.to_obj()))

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
                                slot=str(
                                    epoch_no * spec_deneb.SLOTS_PER_EPOCH + slot_no
                                ),
                            )
                            for slot_no in range(spec_deneb.SLOTS_PER_EPOCH)
                        ],
                    )
                ),
            )

        if re.match("/eth/v3/validator/blocks/.*", url.raw_path):
            if execution_payload_blinded:
                _data = SpecBeaconBlock.DenebBlinded(
                    slot=int(url.raw_path.split("/")[-1]),
                    proposer_index=123,
                    parent_root="0xcbe950dda3533e3c257fd162b33d791f9073eb42e4da21def569451e9323c33e",
                    state_root="0xd9f5a83718a7657f50bc3c5be8c2b2fd7f051f44d2962efdde1e30cee881e7f6",
                    # body=...
                ).to_obj()
            else:
                _data = dict(
                    block=SpecBeaconBlock.Deneb(
                        slot=int(url.raw_path.split("/")[-1]),
                        proposer_index=123,
                        parent_root="0xcbe950dda3533e3c257fd162b33d791f9073eb42e4da21def569451e9323c33e",
                        state_root="0xd9f5a83718a7657f50bc3c5be8c2b2fd7f051f44d2962efdde1e30cee881e7f6",
                        # body=...
                    ).to_obj(),
                )

            response = SchemaBeaconAPI.ProduceBlockV3Response(
                version=SchemaBeaconAPI.BeaconBlockVersion.DENEB,
                execution_payload_blinded=execution_payload_blinded,
                execution_payload_value=str(random.randint(0, 10_000_000)),
                consensus_block_value=str(random.randint(0, 10_000_000)),
                data=_data,
            )
            return CallbackResult(body=msgspec.json.encode(response))

        if re.match("/eth/v1/validator/attestation_data", url.raw_path):
            att_data = AttestationData(
                slot=int(url.query["slot"]),
                index=int(url.query["committee_index"]),
                beacon_block_root="0x" + os.urandom(32).hex(),
            )
            return CallbackResult(payload=dict(data=att_data.to_obj()))

        if re.match("/eth/v1/validator/aggregate_attestation", url.raw_path):
            aggregate_attestation = SpecAttestation.AttestationDeneb(
                aggregation_bits=Bitlist[spec_deneb.MAX_VALIDATORS_PER_COMMITTEE](
                    random.choice([0, 1])
                    for _ in range(spec_deneb.MAX_VALIDATORS_PER_COMMITTEE)
                ),
                data=AttestationData(
                    slot=int(url.query["slot"]),
                    index=123,
                    beacon_block_root="0x" + os.urandom(32).hex(),
                    source=Checkpoint(
                        epoch=2,
                        root="0x" + os.urandom(32).hex(),
                    ),
                    target=Checkpoint(
                        epoch=3,
                        root="0x" + os.urandom(32).hex(),
                    ),
                ),
                signature="0x" + os.urandom(96).hex(),
            )
            return CallbackResult(payload=dict(data=aggregate_attestation.to_obj()))

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
                aggregation_bits=Bitlist[
                    spec_deneb.TARGET_AGGREGATORS_PER_SYNC_SUBCOMMITTEE
                ](
                    random.choice([0, 1])
                    for _ in range(spec_deneb.TARGET_AGGREGATORS_PER_SYNC_SUBCOMMITTEE)
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
                duty_slot = epoch_no * spec_deneb.SLOTS_PER_EPOCH + random.randint(
                    0,
                    spec_deneb.SLOTS_PER_EPOCH,
                )
                attester_duties.append(
                    SchemaBeaconAPI.AttesterDuty(
                        pubkey=v.pubkey,
                        validator_index=str(v.index),
                        committee_index=str(
                            random.randint(
                                0,
                                spec_deneb.TARGET_AGGREGATORS_PER_COMMITTEE,
                            )
                        ),
                        committee_length=str(
                            spec_deneb.TARGET_AGGREGATORS_PER_COMMITTEE
                        ),
                        committees_at_slot=str(random.randint(0, 10)),
                        validator_committee_index=str(
                            random.randint(
                                0,
                                spec_deneb.TARGET_AGGREGATORS_PER_COMMITTEE,
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

        if re.match("/eth/v1/beacon/pool/attestations", url.raw_path):
            return CallbackResult(status=200)

        if re.match("/eth/v1/validator/aggregate_and_proofs", url.raw_path):
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
