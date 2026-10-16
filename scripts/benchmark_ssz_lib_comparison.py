import logging
import time
from pathlib import Path

from ssz_z import get_type

SIGNED_BLOCK = get_type("SignedBeaconBlock", fork="electra")

BLOCKS_DIR = Path("/tmp/beacon_blocks")  # noqa: S108

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def benchmark_json(json_blocks: list[bytes]) -> None:
    if not json_blocks:
        logger.warning("No JSON blocks found in %s", BLOCKS_DIR / "json")
        return

    decode_seconds = 0.0
    encode_seconds = 0.0
    for block_json in json_blocks:
        started = time.perf_counter()
        decoded = SIGNED_BLOCK.load_json(block_json, wrapped=True)
        decode_seconds += time.perf_counter() - started
        started = time.perf_counter()
        decoded.to_json()
        encode_seconds += time.perf_counter() - started

    logger.info(
        "Lodestar-Z JSON decode: %.2f ms/block",
        1000 * decode_seconds / len(json_blocks),
    )
    logger.info(
        "Lodestar-Z JSON encode: %.2f ms/block",
        1000 * encode_seconds / len(json_blocks),
    )


def benchmark_ssz(ssz_blocks: list[bytes]) -> None:
    if not ssz_blocks:
        logger.warning("No SSZ blocks found in %s", BLOCKS_DIR / "ssz")
        return

    decode_seconds = 0.0
    encode_seconds = 0.0
    for block_ssz in ssz_blocks:
        started = time.perf_counter()
        decoded = SIGNED_BLOCK.load_ssz(block_ssz)
        decode_seconds += time.perf_counter() - started
        started = time.perf_counter()
        encoded = decoded.to_ssz()
        encode_seconds += time.perf_counter() - started
        assert block_ssz == encoded  # noqa: S101

    logger.info(
        "Lodestar-Z SSZ load/validate: %.2f ms/block",
        1000 * decode_seconds / len(ssz_blocks),
    )
    logger.info(
        "Lodestar-Z SSZ export: %.2f ms/block",
        1000 * encode_seconds / len(ssz_blocks),
    )


if __name__ == "__main__":
    benchmark_json(
        [path.read_bytes() for path in sorted((BLOCKS_DIR / "json").glob("*.json"))]
    )
    benchmark_ssz(
        [path.read_bytes() for path in sorted((BLOCKS_DIR / "ssz").glob("*.ssz"))]
    )
