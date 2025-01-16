import argparse
from collections.abc import Sequence
from logging import getLevelNamesMapping
from urllib.parse import urlparse

import msgspec

from spec.configs import Network


class CLIArgs(msgspec.Struct, kw_only=True):
    network: Network
    remote_signer_url: str
    beacon_node_urls: list[str]
    beacon_node_urls_proposal: list[str]
    attestation_consensus_threshold: int
    fee_recipient: str
    data_dir: str
    graffiti: bytes
    gas_limit: int
    use_external_builder: bool
    builder_boost_factor: int
    metrics_address: str
    metrics_port: int
    metrics_multiprocess_mode: bool
    log_level: str


def _validate_url(url: str) -> str:
    parsed = urlparse(url)
    if not (parsed.scheme and parsed.netloc):
        raise ValueError(f"Invalid URL: {url}")
    return url


def _validate_comma_separated_strings(
    input_string: str, entity_name: str, min_values_required: int = 0
) -> list[str]:
    items = [item.strip() for item in input_string.split(",") if item.strip()]
    if len(items) < min_values_required:
        raise ValueError(f"Not enough {entity_name}s provided")
    if len(items) != len(set(items)):
        raise ValueError(f"{entity_name}s must be unique: {items}")
    return items


def _process_attestation_consensus_threshold(
    value: int | None, beacon_node_urls: list[str]
) -> int:
    if value is None:
        # If no value provided, default to a majority of beacon nodes
        return len(beacon_node_urls) // 2 + 1

    if value <= 0:
        raise ValueError(f"Invalid value for attestation_consensus_threshold: {value}")

    if len(beacon_node_urls) < value:
        raise ValueError(
            f"Invalid value for attestation_consensus_threshold ({value})"
            f" with {len(beacon_node_urls)} beacon node(s)"
        )

    return value


def _process_fee_recipient(input_string: str) -> str:
    _fee_recipient_byte_length = 20

    if (
        not input_string.startswith("0x")
        or len(input_string) != 2 + 2 * _fee_recipient_byte_length
    ):
        raise ValueError(f"Invalid fee recipient: {input_string}")

    try:
        _ = bytes.fromhex(input_string[2:])
    except ValueError as e:
        raise ValueError(f"Invalid fee recipient {input_string}: {e!r}") from e
    else:
        return input_string


def _process_graffiti(graffiti: str) -> bytes:
    _graffiti_max_bytes = 32

    encoded = graffiti.encode("utf-8").ljust(_graffiti_max_bytes, b"\x00")
    if len(encoded) > _graffiti_max_bytes:
        raise ValueError(
            f"Encoded graffiti exceeds the maximum length of {_graffiti_max_bytes} bytes"
        )
    return encoded


def _process_gas_limit(input_value: int | None, network: Network) -> int:
    if input_value is not None:
        return input_value

    _defaults = {
        Network.MAINNET: 30_000_000,
        Network.GNOSIS: 17_000_000,
        Network.HOLESKY: 36_000_000,
        Network.FETCH: 100_000_000,
    }

    return _defaults[network]


def parse_cli_args(args: Sequence[str]) -> CLIArgs:
    parser = argparse.ArgumentParser(description="Vero validator client.")

    _network_choices = [e.value for e in list(Network)]
    parser.add_argument(
        "--network",
        type=str,
        required=True,
        choices=_network_choices,
        help="The network to use. 'fetch' is a special case where Vero uses the network specs returned by the beacon node(s).",
    )
    parser.add_argument(
        "--remote-signer-url", type=str, required=True, help="URL of the remote signer."
    )
    parser.add_argument(
        "--beacon-node-urls",
        type=str,
        required=True,
        help="A comma-separated list of beacon node URLs.",
    )
    parser.add_argument(
        "--beacon-node-urls-proposal",
        type=str,
        required=False,
        default="",
        help="A comma-separated list of beacon node URLs to exclusively use for block proposals.",
    )
    parser.add_argument(
        "--attestation-consensus-threshold",
        type=int,
        required=False,
        default=None,
        help="Specify the required number of beacon nodes that need to agree on the attestation data before the validators proceed to attest. Defaults to a majority of beacon nodes (>50%%) agreeing.",
    )
    parser.add_argument(
        "--fee-recipient",
        type=str,
        required=True,
        help="The fee recipient address to use during block proposals.",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        required=False,
        default="/vero/data",
        help="The directory to use for storing persistent data. Defaults to /vero/data .",
    )
    parser.add_argument(
        "--graffiti",
        type=str,
        required=False,
        default="",
        help="The graffiti string to use during block proposals. Defaults to an empty string.",
    )
    parser.add_argument(
        "--gas-limit",
        type=int,
        required=False,
        default=None,
        help="The gas limit value to pass on to external block builders during validator registrations. See the docs for more details.",
    )
    parser.add_argument(
        "--use-external-builder",
        action="store_true",
        help="Provide this flag to submit validator registrations to external builders.",
    )
    parser.add_argument(
        "--builder-boost-factor",
        type=int,
        required=False,
        default=90,
        help="A percentage multiplier applied to externally built blocks when comparing their value to locally built blocks. The externally built block is only chosen if its value, post-multiplication, is higher than the locally built block's value. Defaults to 90.",
    )
    parser.add_argument(
        "--metrics-address",
        type=str,
        required=False,
        default="localhost",
        help="The metrics server listen address. Defaults to localhost.",
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        required=False,
        default=8000,
        help="The metrics server port number. Defaults to 8000.",
    )
    parser.add_argument(
        "--metrics-multiprocess-mode",
        action="store_true",
        help="Provide this flag to collect metrics from all processes. This comes with some limitations, notably no cpu and memory metrics. See https://prometheus.github.io/client_python/multiprocess/ .",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=getLevelNamesMapping().keys(),
        help="The logging level to use. Defaults to INFO.",
    )

    parsed_args = parser.parse_args(args=args)

    try:
        # Process and validate parsed args
        beacon_node_urls = [
            _validate_url(url)
            for url in _validate_comma_separated_strings(
                input_string=parsed_args.beacon_node_urls,
                entity_name="beacon node url",
                min_values_required=1,
            )
        ]
        network = Network(parsed_args.network)
        return CLIArgs(
            network=network,
            remote_signer_url=_validate_url(parsed_args.remote_signer_url),
            beacon_node_urls=beacon_node_urls,
            beacon_node_urls_proposal=[
                _validate_url(url)
                for url in _validate_comma_separated_strings(
                    input_string=parsed_args.beacon_node_urls_proposal,
                    entity_name="proposal beacon node url",
                    min_values_required=0,
                )
            ],
            attestation_consensus_threshold=_process_attestation_consensus_threshold(
                value=parsed_args.attestation_consensus_threshold,
                beacon_node_urls=beacon_node_urls,
            ),
            fee_recipient=_process_fee_recipient(parsed_args.fee_recipient),
            data_dir=parsed_args.data_dir,
            graffiti=_process_graffiti(parsed_args.graffiti),
            gas_limit=_process_gas_limit(
                input_value=parsed_args.gas_limit, network=network
            ),
            use_external_builder=parsed_args.use_external_builder,
            builder_boost_factor=parsed_args.builder_boost_factor,
            metrics_address=parsed_args.metrics_address,
            metrics_port=parsed_args.metrics_port,
            metrics_multiprocess_mode=parsed_args.metrics_multiprocess_mode,
            log_level=parsed_args.log_level,
        )
    except ValueError as e:
        parser.error(repr(e))
