import argparse
import sys
from logging import getLevelNamesMapping
from pathlib import Path

from pydantic import BaseModel, HttpUrl, field_validator, ValidationError


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
    log_level: str

    @staticmethod
    def _validate_beacon_node_urls(input_string: str) -> list[str]:
        urls = [u.strip() for u in input_string.split(",") if len(u.strip()) > 0]

        if len(urls) == 0:
            raise ValueError("no beacon node urls provided")

        if len(urls) != len(set(urls)):
            raise ValueError(f"Beacon node urls must be unique: {urls}")

        return urls

    @field_validator("beacon_node_urls", mode="before")
    def validate_beacon_node_urls(cls, v: str) -> list[str]:
        return cls._validate_beacon_node_urls(input_string=v)

    @field_validator("beacon_node_urls_proposal", mode="before")
    def validate_beacon_node_urls_proposal(cls, v: str | None) -> list[str]:
        return [] if v is None else cls._validate_beacon_node_urls(input_string=v)

    @field_validator("fee_recipient")
    def validate_fee_recipient(cls, v: str) -> str:
        _error_msg = "fee recipient must be a valid hex string starting with 0x"
        if len(v) < 42 or not v.startswith("0x"):
            raise ValueError(_error_msg)
        try:
            bytes.fromhex(v[2:])
            return v
        except ValueError:
            raise ValueError(_error_msg)

    @field_validator("graffiti", mode="before")
    def validate_graffiti(cls, v: str) -> bytes:
        encoded = v.encode("utf-8").ljust(32, b"\x00")
        if len(v) > 32:
            raise ValueError("Encoded graffiti exceeds the maximum length of 32 bytes")
        return encoded


def parse_cli_args() -> CLIArgs:
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
        "--log-level",
        type=str,
        default="INFO",
        choices=getLevelNamesMapping().keys(),
        help="The logging level to use. Defaults to INFO.",
    )

    args = parser.parse_args(sys.argv[1:])

    try:
        # Convert parsed args to dictionary and validate using Pydantic model
        validated_args = CLIArgs(**vars(args))
        return validated_args
    except ValidationError as e:
        parser.error(str(e))
