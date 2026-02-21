import logging
import time
from pathlib import Path

import msgspec.json
from grandine_py import ElectraSignedBeaconBlockMainnet

from spec import SpecAttestation, SpecBeaconBlock
from spec.configs import Network, get_network_spec

spec, preset = get_network_spec(network=Network.HOODI)
SpecAttestation.initialize(spec=spec)
SpecBeaconBlock.initialize(spec=spec)

BLOCKS_DIR = Path("/tmp/beacon_blocks")  # noqa: S108

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def json_remerkleable(json_blocks: list[bytes]) -> None:
    total_decode_time: float = 0
    total_encode_time: float = 0
    for block_json in json_blocks:
        decode_start = time.time()
        decoded = SpecBeaconBlock.ElectraBlockSigned.from_obj(
            msgspec.json.decode(block_json)["data"]
        )
        total_decode_time += time.time() - decode_start

        encode_start = time.time()
        _ = msgspec.json.encode(decoded.to_obj())
        total_encode_time += time.time() - encode_start

    decode_time_per_block = total_decode_time / len(json_blocks)
    encode_time_per_block = total_encode_time / len(json_blocks)

    logger.info(
        f"json_remerkleable:decode : {1000 * decode_time_per_block:.2f} ms / block"
    )
    logger.info(
        f"json_remerkleable:encode : {1000 * encode_time_per_block:.2f} ms / block"
    )


def ssz_remerkleable(ssz_blocks: list[bytes]) -> None:
    total_decode_time: float = 0
    total_encode_time: float = 0
    for block_ssz in ssz_blocks:
        decode_start = time.time()
        decoded = SpecBeaconBlock.ElectraBlockSigned.decode_bytes(block_ssz)
        total_decode_time += time.time() - decode_start

        encode_start = time.time()
        encoded = decoded.encode_bytes()
        total_encode_time += time.time() - encode_start

        assert block_ssz == encoded  # noqa: S101

    decode_time_per_block = total_decode_time / len(ssz_blocks)
    encode_time_per_block = total_encode_time / len(ssz_blocks)

    logger.info(
        f"ssz_remerkleable:decode : {1000 * decode_time_per_block:.2f} ms / block"
    )
    logger.info(
        f"ssz_remerkleable:encode : {1000 * encode_time_per_block:.2f} ms / block"
    )


def json_grandine(json_blocks: list[bytes]) -> None:
    total_decode_time: float = 0
    total_encode_time: float = 0
    for block_json in json_blocks:
        decode_start = time.time()
        decoded = ElectraSignedBeaconBlockMainnet.from_json(block_json)
        total_decode_time += time.time() - decode_start

        encode_start = time.time()
        _ = decoded.to_json()
        total_encode_time += time.time() - encode_start

    decode_time_per_block = total_decode_time / len(json_blocks)
    encode_time_per_block = total_encode_time / len(json_blocks)

    logger.info(f"json_grandine:decode : {1000 * decode_time_per_block:.2f} ms / block")
    logger.info(f"json_grandine:encode : {1000 * encode_time_per_block:.2f} ms / block")


def ssz_grandine(ssz_blocks: list[bytes]) -> None:
    total_decode_time: float = 0
    total_encode_time: float = 0
    for block_ssz in ssz_blocks:
        decode_start = time.time()
        decoded = ElectraSignedBeaconBlockMainnet.from_ssz(block_ssz)
        total_decode_time += time.time() - decode_start

        encode_start = time.time()
        encoded = decoded.to_ssz()
        total_encode_time += time.time() - encode_start

        assert block_ssz == encoded  # noqa: S101

    decode_time_per_block = total_decode_time / len(ssz_blocks)
    encode_time_per_block = total_encode_time / len(ssz_blocks)

    logger.info(f"ssz_grandine:decode : {1000 * decode_time_per_block:.2f} ms / block")
    logger.info(f"ssz_grandine:encode : {1000 * encode_time_per_block:.2f} ms / block")


if __name__ == "__main__":
    logger.info("JSON")
    json_blocks = []
    for file in sorted((BLOCKS_DIR / "json").iterdir()):
        if not file.name.endswith(".json"):
            continue
        json_blocks.append(file.read_bytes())
    json_blocks = [json_blocks[0]]
    json_grandine(json_blocks=json_blocks)
    json_remerkleable(json_blocks=json_blocks)

    logger.info("SSZ")
    ssz_blocks = []
    for file in (BLOCKS_DIR / "ssz").iterdir():
        if not file.name.endswith(".ssz"):
            continue
        ssz_blocks.append(file.read_bytes())
    ssz_grandine(ssz_blocks=ssz_blocks)
    ssz_remerkleable(ssz_blocks=ssz_blocks)
