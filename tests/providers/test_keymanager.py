import os
import tracemalloc

from providers import Keymanager
from schemas.keymanager_api import RemoteKey


async def test_keymanager_memory_usage(
    keymanager: Keymanager,
) -> None:
    """
    We load 1,000 keys with random metadata into Keymanager
    and check that memory usage is within reason.
    """
    n = 1_000
    pubkeys = ["0x" + os.urandom(48).hex() for _ in range(n)]

    tracemalloc.start()
    start_snapshot = tracemalloc.take_snapshot()

    await keymanager.import_remote_keys(
        remote_keys=[
            RemoteKey(
                pubkey=pk,
                # Limit the number of unique signers to 100
                url=f"http://signer-{idx % 100}",
            )
            for idx, pk in enumerate(pubkeys)
        ]
    )

    fr = "0x" + os.urandom(20).hex()
    gl = str(100_000_000)
    graffiti = "0x" + os.urandom(100).hex()
    for pk in pubkeys:
        keymanager.set_fee_recipient(pubkey=pk, fee_recipient=fr)
        keymanager.set_gas_limit(pubkey=pk, gas_limit=gl)
        keymanager.set_graffiti(pubkey=pk, graffiti=graffiti)

    end_snapshot = tracemalloc.take_snapshot()

    # Compare memory usage
    diff = end_snapshot.compare_to(start_snapshot, "lineno")

    total_memory_increase = sum(d.size_diff for d in diff)
    per_key_memory = total_memory_increase / n

    # Every key with all of its metadata and instantiated remote signer
    # should use about 15KiB of memory
    assert per_key_memory / 1024 < 20
