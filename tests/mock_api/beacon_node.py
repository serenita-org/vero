import os
import random
import re
from typing import TYPE_CHECKING, Any

import msgspec
import pytest
from aiohttp.hdrs import CONTENT_TYPE
from aioresponses import CallbackResult, aioresponses
from remerkleable.bitfields import Bitlist, Bitvector

from providers._headers import ContentType
from schemas import SchemaBeaconAPI
from schemas.beacon_api import ForkVersion
from spec import SpecAttestation, SpecBeaconBlock, SpecSyncCommittee
from spec.attestation import AttestationData, Checkpoint
from spec.constants import (
    TARGET_AGGREGATORS_PER_COMMITTEE,
    TARGET_AGGREGATORS_PER_SYNC_SUBCOMMITTEE,
)

if TYPE_CHECKING:
    from yarl import URL

    from providers import BeaconChain
    from schemas.validator import ValidatorIndexPubkey
    from spec.base import SpecFulu


@pytest.fixture(scope="session")
def beacon_node_url() -> str:
    return "http://beacon-node-1:1234"


@pytest.fixture
def execution_payload_blinded(request: pytest.FixtureRequest) -> bool:
    return getattr(request, "param", False)


@pytest.fixture
def response_content_type(request: pytest.FixtureRequest) -> ContentType:
    return getattr(request, "param", ContentType.JSON)


@pytest.fixture
def _mocked_beacon_node_endpoints(
    validators: list[ValidatorIndexPubkey],
    spec: SpecFulu,
    beacon_chain: BeaconChain,
    mocked_responses: aioresponses,
    execution_payload_blinded: bool,
    response_content_type: ContentType,
) -> None:
    def _mocked_beacon_api_endpoints_get(url: URL, **kwargs: Any) -> CallbackResult:
        if re.match("/eth/v1/config/spec", url.raw_path):
            return CallbackResult(payload=dict(data=spec.to_obj()))

        if re.match("/eth/v1/node/version", url.raw_path):
            return CallbackResult(payload=dict(data=dict(version="beacon-node/test")))

        if re.match(r"/eth/v1/validator/duties/proposer/\d+", url.raw_path):
            # This endpoint returns all proposer duties for the epoch
            epoch_no = int(url.raw_path.split("/")[-1])

            proposer_duties = []
            for duty_slot in range(
                epoch_no * spec.SLOTS_PER_EPOCH, (epoch_no + 1) * spec.SLOTS_PER_EPOCH
            ):
                # For our managed validators, only schedule duties for the next 2 slots
                # so we don't block the shutdown_handler for long
                if duty_slot <= beacon_chain.current_slot + 2:
                    proposer = random.choice(validators)
                    proposer_duties.append(
                        SchemaBeaconAPI.ProposerDuty(
                            pubkey=proposer.pubkey,
                            validator_index=str(proposer.index),
                            slot=str(duty_slot),
                        ),
                    )
                else:
                    proposer_duties.append(
                        SchemaBeaconAPI.ProposerDuty(
                            pubkey="0x" + os.urandom(48).hex(),
                            validator_index=str(random.randint(0, 1_000_000)),
                            slot=str(duty_slot),
                        ),
                    )

            return CallbackResult(
                body=msgspec.json.encode(
                    SchemaBeaconAPI.GetProposerDutiesResponse(
                        dependent_root="0xab09edd9380f8451c3ff5c809821174a36dce606fea8b5ea35ea936915dbf889",
                        execution_optimistic=False,
                        data=proposer_duties,
                    )
                ),
            )

        if re.match("/eth/v3/validator/blocks/.*", url.raw_path):
            slot = int(url.raw_path.split("/")[-1])

            block_cls_map = {
                ForkVersion.ELECTRA: SpecBeaconBlock.ElectraBlockContents,
                ForkVersion.FULU: SpecBeaconBlock.ElectraBlockContents,
            }
            blinded_block_cls_map = {
                ForkVersion.ELECTRA: SpecBeaconBlock.ElectraBlindedBlock,
                ForkVersion.FULU: SpecBeaconBlock.ElectraBlindedBlock,
            }

            fork_version = beacon_chain.current_fork_version
            if execution_payload_blinded:
                if fork_version not in blinded_block_cls_map:
                    raise NotImplementedError(
                        f"Unsupported fork version {fork_version}"
                    )

                _data = blinded_block_cls_map[fork_version](
                    slot=slot,
                    proposer_index=123,
                    parent_root="0xcbe950dda3533e3c257fd162b33d791f9073eb42e4da21def569451e9323c33e",
                    state_root="0xd9f5a83718a7657f50bc3c5be8c2b2fd7f051f44d2962efdde1e30cee881e7f6",
                    # body=...
                )
            else:
                if fork_version not in block_cls_map:
                    raise NotImplementedError(
                        f"Unsupported fork version {fork_version}"
                    )

                _data = block_cls_map[fork_version].from_obj(
                    dict(
                        block=dict(
                            slot=slot,
                            proposer_index=123,
                            parent_root="0xcbe950dda3533e3c257fd162b33d791f9073eb42e4da21def569451e9323c33e",
                            state_root="0xd9f5a83718a7657f50bc3c5be8c2b2fd7f051f44d2962efdde1e30cee881e7f6",
                            # body=...
                        ),
                        kzg_proofs=[],
                        blobs=[],
                    )
                )

            exec_payload_value = random.randint(0, 10_000_000)
            consensus_block_value = random.randint(0, 10_000_000)
            headers = {
                CONTENT_TYPE: response_content_type.value,
                "Eth-Consensus-Version": fork_version.value,
                "Eth-Execution-Payload-Blinded": str(execution_payload_blinded),
                "Eth-Execution-Payload-Value": str(exec_payload_value),
                "Eth-Consensus-Block-Value": str(consensus_block_value),
            }

            if response_content_type == ContentType.OCTET_STREAM:
                return CallbackResult(body=_data.encode_bytes(), headers=headers)

            return CallbackResult(
                body=msgspec.json.encode(
                    SchemaBeaconAPI.ProduceBlockV3Response(
                        version=fork_version,
                        execution_payload_blinded=execution_payload_blinded,
                        execution_payload_value=str(exec_payload_value),
                        consensus_block_value=str(consensus_block_value),
                        data=_data.to_obj(),
                    )
                ),
                headers=headers,
            )

        if re.match("/eth/v1/validator/attestation_data", url.raw_path):
            att_data = AttestationData(
                slot=int(url.query["slot"]),
                index=int(url.query["committee_index"]),
                beacon_block_root="0x9f19cc6499596bdf19be76d80b878ee3326e68cf2ed69cbada9a1f4fe13c51b3",
                source=Checkpoint(
                    epoch=beacon_chain.current_epoch,
                ),
            )
            return CallbackResult(payload=dict(data=att_data.to_obj()))

        if re.match("/eth/v2/validator/aggregate_attestation", url.raw_path):
            if beacon_chain.current_fork_version not in (
                ForkVersion.ELECTRA,
                ForkVersion.FULU,
            ):
                raise NotImplementedError(
                    f"Unsupported fork version {beacon_chain.current_fork_version}"
                )

            fork_version = beacon_chain.current_fork_version

            _committee_bits = Bitvector[spec.MAX_COMMITTEES_PER_SLOT](
                False for _ in range(spec.MAX_COMMITTEES_PER_SLOT)
            )
            _committee_bits[int(url.query["committee_index"])] = True
            _agg_bitlist_size = (
                spec.MAX_VALIDATORS_PER_COMMITTEE * spec.MAX_COMMITTEES_PER_SLOT
            )
            # Populating the full bitlist is expensive
            # -> a smaller agg bits bitlist is fine for testing purposes too
            _agg_bits = [1, 0, 1, 0, 1, 1, 1, 0, 1, 1]
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

            return_list = []
            for validator in validators:
                if validator.pubkey not in ids:
                    continue

                if statuses is not None and validator.status.value not in statuses:
                    continue

                return_list.append(
                    SchemaBeaconAPI.ValidatorInfo(
                        index=str(validator.index),
                        status=validator.status,
                        validator=SchemaBeaconAPI.Validator(pubkey=validator.pubkey),
                    )
                )

            return CallbackResult(
                body=msgspec.json.encode(
                    SchemaBeaconAPI.GetStateValidatorsResponse(
                        execution_optimistic=False,
                        data=return_list,
                    )
                )
            )

        if re.match("/eth/v1/validator/prepare_beacon_proposer", url.raw_path):
            return CallbackResult(status=200)

        if re.match("/eth/v1/validator/register_validator", url.raw_path):
            return CallbackResult(status=200)

        if re.match("/eth/v2/beacon/blocks", url.raw_path):
            headers = kwargs["headers"]
            fork_version = ForkVersion[headers["Eth-Consensus-Version"].upper()]

            if fork_version not in (
                ForkVersion.ELECTRA,
                ForkVersion.FULU,
            ):
                raise NotImplementedError(f"Unsupported fork version {fork_version}")

            assert fork_version == beacon_chain.current_fork_version

            if fork_version in (ForkVersion.ELECTRA, ForkVersion.FULU):
                if headers[CONTENT_TYPE] == ContentType.JSON.value:
                    _ = SpecBeaconBlock.ElectraBlockContentsSigned.from_obj(
                        msgspec.json.decode(kwargs["data"].decode())
                    )
                else:
                    _ = SpecBeaconBlock.ElectraBlockContentsSigned.decode_bytes(
                        kwargs["data"]
                    )

            return CallbackResult(status=200)

        if re.match("/eth/v2/beacon/blinded_blocks", url.raw_path):
            headers = kwargs["headers"]
            fork_version = ForkVersion[headers["Eth-Consensus-Version"].upper()]

            if fork_version not in (
                ForkVersion.ELECTRA,
                ForkVersion.FULU,
            ):
                raise NotImplementedError(f"Unsupported fork version {fork_version}")

            assert fork_version == beacon_chain.current_fork_version

            if fork_version in (ForkVersion.ELECTRA, ForkVersion.FULU):
                if headers[CONTENT_TYPE] == ContentType.JSON.value:
                    _ = SpecBeaconBlock.ElectraBlindedBlockSigned.from_obj(
                        msgspec.json.decode(kwargs["data"].decode())
                    )
                else:
                    _ = SpecBeaconBlock.ElectraBlindedBlockSigned.decode_bytes(
                        kwargs["data"]
                    )

            return CallbackResult(status=200)

        if re.match(r"/eth/v1/validator/duties/attester/\d+", url.raw_path):
            epoch_no = int(url.raw_path.split("/")[-1])

            # This endpoint returns only duties for the validators
            # specified in the response
            attester_duties = []
            for v in validators:
                # We want to schedule our validator's duties to happen soon
                last_slot_in_epoch = (epoch_no + 1) * spec.SLOTS_PER_EPOCH - 1
                if beacon_chain.current_slot == last_slot_in_epoch:
                    # Last slot in epoch, don't schedule anything anymore,
                    # we'll attest in the next epoch
                    continue

                # Schedule our validators to attest in the next scheduled slot
                duty_slot = beacon_chain.current_slot + 1
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
            _ = msgspec.json.decode(
                kwargs["data"].decode(),
                type=list[SchemaBeaconAPI.SubscribeToBeaconCommitteeSubnetRequestBody],
            )
            return CallbackResult(status=200)

        if re.match("/eth/v2/beacon/pool/attestations", url.raw_path):
            if beacon_chain.current_fork_version in (
                ForkVersion.ELECTRA,
                ForkVersion.FULU,
            ):
                attestations = msgspec.json.decode(
                    kwargs["data"].decode(),
                    type=list[SchemaBeaconAPI.SingleAttestation],
                )
                attestation = attestations[0]
            else:
                raise NotImplementedError(
                    f"Unsupported fork version {beacon_chain.current_fork_version}"
                )

            assert (
                attestation.data.beacon_block_root
                == "0x9f19cc6499596bdf19be76d80b878ee3326e68cf2ed69cbada9a1f4fe13c51b3"
            )

            return CallbackResult(status=200)

        if re.match("/eth/v2/validator/aggregate_and_proofs", url.raw_path):
            data_list = msgspec.json.decode(kwargs["data"])
            assert len(data_list) == 1
            data = data_list[0]

            assert data["message"]["aggregator_index"] == "1"
            aggregate = data["message"]["aggregate"]

            if beacon_chain.current_fork_version in (
                ForkVersion.ELECTRA,
                ForkVersion.FULU,
            ):
                assert aggregate["committee_bits"] == "0x0040000000000000"
                assert aggregate["aggregation_bits"] == "0x7507"
            else:
                raise NotImplementedError(
                    f"Unsupported fork version {beacon_chain.current_fork_version}"
                )
            return CallbackResult(status=200)

        if re.match(r"/eth/v1/validator/duties/sync/\d+", url.raw_path):
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
