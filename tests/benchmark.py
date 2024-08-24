import math
import os
import random
import time

from remerkleable.bitfields import Bitlist

from spec.attestation import Attestation, AttestationData, Checkpoint
from spec.common import MAX_VALIDATORS_PER_COMMITTEE
from concurrent.futures import ProcessPoolExecutor


# Function to process a batch of attestations
def process_batch(batch):
    return [att.to_obj() for att in batch]


def run():
    # Generate a lot of attestations
    attestations = [
        Attestation(
            aggregation_bits=Bitlist[MAX_VALIDATORS_PER_COMMITTEE](
                random.choice([True, False]) for _ in range(2000)
            ),
            data=AttestationData(
                slot=73123,
                index=random.randint(0, 2000),
                beacon_block_root="0x8a8d60f0036653cb985c3cc8e6ee25ff6563ff232660493be5b7b97d0aecefa7",
                source=Checkpoint(
                    epoch=123,
                    root="0x8a8d60f0036653cb985c3cc8e6ee25ff6563ff232660493be5b7b97d0aecefa7",
                ),
                target=Checkpoint(
                    epoch=124,
                    root="0x8a8d60f0036653cb985c3cc8e6ee25ff6563ff232660493be5b7b97d0aecefa7",
                ),
            ),
            signature=os.urandom(96).hex(),
        )
        for i in range(100_000)
    ]

    start_time = time.time()
    orig = [a.to_obj() for a in attestations]
    time_original = time.time() - start_time
    print(f"Time original: {time_original}")

    # Processes

    # Get the number of CPU cores
    num_cores = os.cpu_count()

    # Divide attestations into X batches where X = number of CPU cores
    batch_size = math.ceil(len(attestations) / num_cores)
    batches = [
        attestations[i : i + batch_size]
        for i in range(0, len(attestations), batch_size)
    ]

    start_time_mp = time.time()
    # Use a ProcessPoolExecutor to parallelize the to_obj() calls
    with ProcessPoolExecutor(max_workers=num_cores) as executor:
        mp = [
            obj
            for batch_result in executor.map(process_batch, batches)
            for obj in batch_result
        ]

    time_mp = time.time() - start_time_mp
    print(f"Time ProcessPoolExecutor: {time_mp} -> {100*time_mp / time_original:.2f}%")
    assert orig == mp

    start_time_cache = time.time()
    first_att_obj = attestations[0].to_obj()
    cache = [first_att_obj]
    for attestation in attestations[1:]:
        att_obj = {
            "data": {
                "slot": first_att_obj["data"]["slot"],
                "index": attestation.data.index.to_obj(),  # Assuming this changes
                "beacon_block_root": first_att_obj["data"]["beacon_block_root"],
                "source": first_att_obj["data"]["source"],
                # Assuming this does not change
                "target": first_att_obj["data"]["target"],
                # Assuming this does not change
            },
            "aggregation_bits": attestation.aggregation_bits.to_obj(),
            "signature": attestation.signature.to_obj(),
        }
        cache.append(att_obj)

    time_cache = time.time() - start_time_cache
    print(f"Time cache: {time_cache} -> {100*time_cache / time_original:.2f}%")
    assert orig == cache

    # Cache + list comprehension
    start_time_cache_comp = time.time()
    first_att_obj = attestations[0].to_obj()
    cache_comp = (
        [first_att_obj]
        + [
            {
                "data": {
                    "slot": first_att_obj["data"]["slot"],
                    "index": attestation.data.index.to_obj(),  # Assuming this changes
                    "beacon_block_root": first_att_obj["data"]["beacon_block_root"],
                    "source": first_att_obj["data"]["source"],
                    # Assuming this does not change
                    "target": first_att_obj["data"]["target"],
                    # Assuming this does not change
                },
                "aggregation_bits": attestation.aggregation_bits.to_obj(),
                "signature": attestation.signature.to_obj(),
            }
            for attestation in attestations[1:]
        ]
    )

    time_cache_comp = time.time() - start_time_cache_comp
    print(
        f"Time cache comp: {time_cache_comp} -> {100 * time_cache_comp / time_original:.2f}%"
    )
    assert orig == cache_comp


if __name__ == "__main__":
    run()
