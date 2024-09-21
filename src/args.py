import argparse
from collections.abc import Sequence
from logging import getLevelNamesMapping
from pathlib import Path

from pydantic import BaseModel, HttpUrl, ValidationError, field_validator

_fee_recipient_bytes = 20
_graffiti_max_bytes = 32


class CLIArgs(BaseModel):
    remote_signer_url: HttpUrl
    beacon_node_urls: list[HttpUrl]
    beacon_node_urls_proposal: list[HttpUrl] = []
    fee_recipient: str
    data_dir: Path
    graffiti: bytes
    gas_limit: int
    use_external_builder: bool = False
    builder_boost_factor: int
    metrics_address: str
    metrics_port: int
    metrics_multiprocess_mode: bool = False
    log_level: str

    @staticmethod
    def _validate_comma_separated_strings(
        input_string: str, entity_name: str
    ) -> list[str]:
        items = [
            item.strip() for item in input_string.split(",") if len(item.strip()) > 0
        ]

        if len(items) == 0:
            raise ValueError(f"no {entity_name}s provided")

        if len(items) != len(set(items)):
            raise ValueError(f"{entity_name}s must be unique: {items}")

        return items

    @staticmethod
    def _validate_hex_strings(items: list[str], byte_length: int) -> None:
        invalid_items = []
        for item in items:
            if not item.startswith("0x") or len(item) != 2 + 2 * byte_length:
                invalid_items.append(item)
                continue

            try:
                bytes.fromhex(item[2:])
            except ValueError:
                invalid_items.append(item)

        if invalid_items:
            raise ValueError(f"invalid hex inputs: {invalid_items}")

    @field_validator("beacon_node_urls", mode="before")
    def validate_beacon_node_urls(cls, v: str) -> list[str]:
        return cls._validate_comma_separated_strings(
            input_string=v, entity_name="beacon node url"
        )

    @field_validator("beacon_node_urls_proposal", mode="before")
    def validate_beacon_node_urls_proposal(cls, v: str | None) -> list[str]:
        return (
            []
            if v is None
            else cls._validate_comma_separated_strings(
                input_string=v, entity_name="beacon node url"
            )
        )

    @field_validator("fee_recipient")
    def validate_fee_recipient(cls, v: str) -> str:
        cls._validate_hex_strings(items=[v], byte_length=_fee_recipient_bytes)
        return v

    @field_validator("graffiti", mode="before")
    def validate_graffiti(cls, v: str) -> bytes:
        encoded = v.encode("utf-8").ljust(_graffiti_max_bytes, b"\x00")
        if len(v) > _graffiti_max_bytes:
            raise ValueError(
                f"encoded graffiti exceeds the maximum length of {_graffiti_max_bytes} bytes"
            )
        return encoded


def parse_cli_args(args: Sequence[str]) -> CLIArgs:
    parser = argparse.ArgumentParser(description="Vero validator client.")

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
        help="A comma-separated list of beacon node URLs to exclusively use for block proposals.",
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
        default=30_000_000,
        help="The gas limit to be used when building blocks. Defaults to 30,000,000.",
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
        # Convert parsed args to dictionary and validate using Pydantic model
        return CLIArgs(**vars(parsed_args))
    except ValidationError as e:
        parser.error(str(e))
