import ipaddress

import msgspec
from yarl import URL

from args import CLIArgs
from schemas.keymanager_api import (
    BuilderConfig,
    BuilderEntry,
    ResolvedBuilderConfig,
    ResolvedBuilderEntry,
)


def get_default_auth_data(url: URL) -> bytes:
    host = url.host
    if host is None:
        raise ValueError(f"No host in URL: {url}")

    if ":" in host:  # IPv6 literal
        host = f"[{ipaddress.IPv6Address(host).compressed}]"

    return host.encode("ascii")


def _default[T](value: T | msgspec.UnsetType, fallback: T) -> T:
    return fallback if value is msgspec.UNSET else value


def _uint64(value: str) -> str:
    if not 0 <= int(value) < 2**64:
        raise ValueError("Builder configuration values must fit in uint64")
    return value


def resolve_builder_config(
    config: BuilderConfig, cli_args: CLIArgs
) -> ResolvedBuilderConfig:
    min_bid = _uint64(_default(config.min_bid, str(cli_args.builder_min_bid)))
    boost = _uint64(
        _default(config.builder_boost_factor, str(cli_args.builder_boost_factor))
    )
    entries = _default(
        config.builders, [BuilderEntry(url=url) for url in cli_args.builder_urls]
    )
    builders = []
    identities = set()
    for entry in entries:
        if any(
            char.isspace() or ord(char) < 32 or ord(char) == 127 for char in entry.url
        ):
            raise ValueError(
                "Builder URL must not contain whitespace or control characters"
            )
        url = URL(entry.url)
        if url.scheme not in {"http", "https"} or not url.host:
            raise ValueError("Builder URL must be an absolute HTTP(S) URL")
        # Accessing port validates an explicitly supplied port as well.
        _ = url.port
        auth_data = _default(entry.auth_data, "0x" + get_default_auth_data(url).hex())
        identity = (entry.url, bytes.fromhex(auth_data[2:]))
        if identity in identities:
            raise ValueError("Duplicate builder URL and auth_data")
        identities.add(identity)
        builders.append(
            ResolvedBuilderEntry(
                url=entry.url,
                auth_data="0x" + identity[1].hex(),
                builder_pubkeys=_default(entry.builder_pubkeys, []),
                max_execution_payment=_uint64(
                    _default(
                        entry.max_execution_payment,
                        str(cli_args.builder_max_execution_payment),
                    )
                ),
                min_bid=_uint64(_default(entry.min_bid, min_bid)),
                builder_boost_factor=_uint64(
                    _default(entry.builder_boost_factor, boost)
                ),
            )
        )
    return ResolvedBuilderConfig(
        min_bid=min_bid, builder_boost_factor=boost, builders=builders
    )


def bid_score(value: int, boost_factor: int) -> tuple[int, int]:
    # The maximum uint64 encodes an unconditional preference for a builder bid.
    return (int(boost_factor == 2**64 - 1), value * boost_factor)
