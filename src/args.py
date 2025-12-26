import argparse
import logging
import sys
from logging import getLevelNamesMapping
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import msgspec

from observability import get_service_version
from spec.configs import Network
from spec.utils import decode_graffiti, encode_graffiti

if TYPE_CHECKING:
    from collections.abc import Sequence


class CLIArgs(msgspec.Struct, kw_only=True):
    network: Network
    network_custom_config_path: str | None
    remote_signer_url: str | None
    beacon_node_urls: list[str]
    beacon_node_urls_proposal: list[str]
    attestation_consensus_threshold: int
    fee_recipient: str
    data_dir: str
    graffiti: bytes
    gas_limit: int
    use_external_builder: bool
    builder_boost_factor: int
    enable_doppelganger_detection: bool
    enable_keymanager_api: bool
    keymanager_api_token_file_path: Path
    keymanager_api_address: str
    keymanager_api_port: int
    metrics_address: str
    metrics_port: int
    log_level: int
    disable_slashing_detection: bool


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


def _process_gas_limit(input_value: int | None, network: Network) -> int:
    if input_value is not None:
        return input_value

    _defaults = {
        Network.MAINNET: 60_000_000,
        Network.GNOSIS: 17_000_000,
        Network.HOODI: 60_000_000,
        Network.CHIADO: 17_000_000,
        Network.CUSTOM: 100_000_000,
    }

    return _defaults[network]


def log_cli_arg_values(validated_args: CLIArgs) -> None:
    logger = logging.getLogger(__name__)

    for action in get_parser()._actions:  # noqa: SLF001
        if action.dest in ("help",):
            continue

        validated_arg_value = getattr(
            validated_args, action.dest.removeprefix("DANGER____")
        )
        if isinstance(validated_arg_value, list):
            validated_arg_value = ",".join(validated_arg_value)
        elif action.dest == "graffiti":
            validated_arg_value = decode_graffiti(validated_arg_value)
        elif action.dest == "log_level":
            validated_arg_value = logging.getLevelName(validated_arg_value)

        if action.default != validated_arg_value:
            logger.info(f"{action.dest}: {validated_arg_value}")


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Vero validator client.")

    mutually_exclusive_group_key_source = parser.add_mutually_exclusive_group(
        required=True
    )

    _network_choices = [e.value for e in list(Network) if e != Network._TESTS]  # noqa: SLF001
    parser.add_argument(
        "--network",
        type=str,
        required=True,
        choices=_network_choices,
        help="The network to use. `custom` is a special case where Vero loads the network spec from the file specified using `--network-custom-config-path`",
    )
    parser.add_argument(
        "--network-custom-config-path",
        type=str,
        required=False,
        default=None,
        help="Path to a custom network configuration file from which to load the network specs.",
    )
    mutually_exclusive_group_key_source.add_argument(
        "--remote-signer-url",
        type=str,
        required=False,
        help="URL of the remote signer.",
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
        default=f"Vero {get_service_version()}",
        help="The graffiti string to use during block proposals. Defaults to 'Vero <version>'.",
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
        "--enable-doppelganger-detection",
        action="store_true",
        help="Enables doppelganger detection.",
    )
    mutually_exclusive_group_key_source.add_argument(
        "--enable-keymanager-api",
        action="store_true",
        help="Enables the Keymanager API.",
    )
    parser.add_argument(
        "--keymanager-api-token-file-path",
        type=str,
        required=False,
        default=None,
        help="Path to a file containing the bearer token used for Keymanager API authentication. If none is provided, a file called 'keymanager-api-token.txt' will be created in Vero's data directory.",
    )
    parser.add_argument(
        "--keymanager-api-address",
        type=str,
        required=False,
        default="localhost",
        help="The Keymanager API server listen address. Defaults to localhost.",
    )
    parser.add_argument(
        "--keymanager-api-port",
        type=int,
        required=False,
        default=8001,
        help="The Keymanager API server port number. Defaults to 8001.",
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
        "--log-level",
        type=str,
        default="INFO",
        choices=getLevelNamesMapping().keys(),
        help="The logging level to use. Defaults to INFO.",
    )
    parser.add_argument(
        "----DANGER----disable-slashing-detection",
        action="store_true",
        help="[DANGEROUS] Disables Vero's proactive slashing detection.",
    )
    return parser


def parse_cli_args(args: Sequence[str]) -> CLIArgs:
    if args == ["--version"]:
        from observability import get_service_version

        print(f"Vero {get_service_version()}")  # noqa: T201
        sys.exit(0)

    parser = get_parser()
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
        if len({urlparse(bn_url).hostname for bn_url in beacon_node_urls}) != len(
            beacon_node_urls
        ):
            parser.error("Beacon node URLs must have unique hostnames.")
        beacon_node_urls_proposal = [
            _validate_url(url)
            for url in _validate_comma_separated_strings(
                input_string=parsed_args.beacon_node_urls_proposal,
                entity_name="proposal beacon node url",
                min_values_required=0,
            )
        ]
        if len(
            {urlparse(bn_url).hostname for bn_url in beacon_node_urls_proposal}
        ) != len(beacon_node_urls_proposal):
            parser.error("Proposal beacon node URLs must have unique hostnames.")
        network = Network(parsed_args.network)

        keymanager_api_token_file_path = (
            parsed_args.keymanager_api_token_file_path
            or Path(parsed_args.data_dir) / "keymanager-api-token.txt"
        )

        validated_args = CLIArgs(
            network=network,
            network_custom_config_path=parsed_args.network_custom_config_path,
            remote_signer_url=_validate_url(parsed_args.remote_signer_url)
            if parsed_args.remote_signer_url is not None
            else None,
            beacon_node_urls=beacon_node_urls,
            beacon_node_urls_proposal=beacon_node_urls_proposal,
            attestation_consensus_threshold=_process_attestation_consensus_threshold(
                value=parsed_args.attestation_consensus_threshold,
                beacon_node_urls=beacon_node_urls,
            ),
            fee_recipient=_process_fee_recipient(parsed_args.fee_recipient),
            data_dir=parsed_args.data_dir,
            graffiti=encode_graffiti(parsed_args.graffiti),
            gas_limit=_process_gas_limit(
                input_value=parsed_args.gas_limit, network=network
            ),
            use_external_builder=parsed_args.use_external_builder,
            builder_boost_factor=parsed_args.builder_boost_factor,
            enable_doppelganger_detection=parsed_args.enable_doppelganger_detection,
            enable_keymanager_api=parsed_args.enable_keymanager_api,
            keymanager_api_token_file_path=Path(keymanager_api_token_file_path),
            keymanager_api_address=parsed_args.keymanager_api_address,
            keymanager_api_port=parsed_args.keymanager_api_port,
            metrics_address=parsed_args.metrics_address,
            metrics_port=parsed_args.metrics_port,
            log_level=logging.getLevelName(parsed_args.log_level),
            disable_slashing_detection=parsed_args.DANGER____disable_slashing_detection,
        )
    except ValueError as e:
        parser.error(repr(e))
    else:
        # For test_parse_cli_args
        if "pytest" in sys.modules:
            log_cli_arg_values(validated_args)

        return validated_args
