import logging
from pathlib import Path
from typing import Any

import pytest

from args import CLIArgs, get_parser, parse_cli_args
from spec.configs import Network
from spec.utils import encode_graffiti

MINIMUM_ARG_LIST = [
    "--network=hoodi",
    "--remote-signer-url=http://signer:9000",
    "--beacon-node-urls=http://beacon-node:5052",
    "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
]


@pytest.mark.parametrize(
    argnames=(
        "list_of_args",
        "expected_error_message",
        "expected_attr_values",
        "expected_log_messages",
    ),
    argvalues=[
        pytest.param(
            [],
            "the following arguments are required: --network, --beacon-node-urls, --fee-recipient\n",
            {},
            [],
            id="No arguments provided",
        ),
        pytest.param(
            [
                "--network=hoodi",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node-1:5052,http://beacon-node-2:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            None,
            {
                "beacon_node_urls": [
                    "http://beacon-node-1:5052",
                    "http://beacon-node-2:5052",
                ],
                "attestation_consensus_threshold": 2,
            },
            [
                "beacon_node_urls: http://beacon-node-1:5052,http://beacon-node-2:5052",
                "attestation_consensus_threshold: 2",
            ],
            id="--beacon-node-urls valid input - multiple values",
        ),
        pytest.param(
            [
                "--network=hoodi",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=   ",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "Not enough beacon node urls provided",
            {},
            [],
            id="--beacon-node-urls invalid input - empty string",
        ),
        pytest.param(
            [
                "--network=sepolia",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "argument --network: invalid choice: 'sepolia'",
            {},
            [],
            id="--network invalid input - unsupported network",
        ),
        pytest.param(
            [
                "--network=hoodi",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node-1:5052,http://beacon-node-2:5052,http://beacon-node-1:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "beacon node urls must be unique",
            {},
            [],
            id="--beacon-node-urls invalid input - duplicate values",
        ),
        pytest.param(
            [
                "--network=hoodi",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node-1:5052,http://beacon-node-1:5053",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "Beacon node URLs must have unique hostnames",
            {},
            [],
            id="--beacon-node-urls invalid input - duplicate hostname",
        ),
        pytest.param(
            [
                "--beacon-node-urls-proposal=http://beacon-node-prop:5052",
                *MINIMUM_ARG_LIST,
            ],
            None,
            {
                "beacon_node_urls": ["http://beacon-node:5052"],
                "beacon_node_urls_proposal": ["http://beacon-node-prop:5052"],
            },
            [
                "beacon_node_urls: http://beacon-node:5052",
                "beacon_node_urls_proposal: http://beacon-node-prop:5052",
            ],
            id="--beacon-node-urls-proposal",
        ),
        pytest.param(
            [
                "--beacon-node-urls-proposal=http://beacon-node-1:5052,http://beacon-node-1:5053",
                *MINIMUM_ARG_LIST,
            ],
            "Proposal beacon node URLs must have unique hostnames",
            {},
            [],
            id="--beacon-node-urls-proposal invalid input - duplicate hostname",
        ),
        pytest.param(
            [
                "--network=hoodi",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node-1:5052,http://beacon-node-2:5052,http://beacon-node-3:5052",
                "--attestation-consensus-threshold=3",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            None,
            {
                "attestation_consensus_threshold": 3,
            },
            [
                "attestation_consensus_threshold: 3",
            ],
            id="--attestation-consensus-threshold override",
        ),
        pytest.param(
            ["--attestation-consensus-threshold=asd", *MINIMUM_ARG_LIST],
            "argument --attestation-consensus-threshold: invalid int value",
            {},
            [],
            id="--attestation-consensus-threshold invalid input - string instead of int",
        ),
        pytest.param(
            ["--attestation-consensus-threshold=2", *MINIMUM_ARG_LIST],
            "Invalid value for attestation_consensus_threshold (2) with 1 beacon node(s)",
            {},
            [],
            id="--attestation-consensus-threshold invalid input - threshold impossible to reach",
        ),
        pytest.param(
            ["--attestation-consensus-threshold=0", *MINIMUM_ARG_LIST],
            "Invalid value for attestation_consensus_threshold: 0",
            {},
            [],
            id="--attestation-consensus-threshold invalid input - 0",
        ),
        pytest.param(
            [
                "--network=hoodi",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c",
            ],
            "Invalid fee recipient: 0x1c6c",
            {},
            [],
            id="--fee-recipient invalid input - wrong length",
        ),
        pytest.param(
            [
                "--network=hoodi",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "Invalid fee recipient: 1c6c9654",
            {},
            [],
            id="--fee-recipient invalid input - no 0x prefix",
        ),
        pytest.param(
            [
                "--network=hoodi",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0xGGGG96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "Invalid fee recipient 0xGGGG96549debfc6aaec7631051b84ce9a6e11ad2: ValueError('non-hexadecimal number found",
            {},
            [],
            id="--fee-recipient invalid input - non-hex character",
        ),
        pytest.param(
            ["--data-dir=data", *MINIMUM_ARG_LIST],
            None,
            {"data_dir": "data"},
            ["data_dir: data"],
            id="--data-dir - relative path",
        ),
        pytest.param(
            ["--data-dir=/tmp/data", *MINIMUM_ARG_LIST],
            None,
            {"data_dir": "/tmp/data"},
            ["data_dir: /tmp/data"],
            id="--data-dir - absolute path",
        ),
        pytest.param(
            ["--graffiti=short", *MINIMUM_ARG_LIST],
            None,
            {"graffiti": b"short".ljust(32, b"\x00")},
            ["graffiti: short"],
            id="--graffiti valid input",
        ),
        pytest.param(
            ["--graffiti=🐟 💰 ❓", *MINIMUM_ARG_LIST],
            None,
            {"graffiti": "🐟 💰 ❓".encode().ljust(32, b"\x00")},
            ["graffiti: 🐟 💰 ❓"],
            id="--graffiti valid input - emoji",
        ),
        pytest.param(
            [
                "--graffiti=waaaaaaaay_toooooo_loooooooooooooooooong",
                *MINIMUM_ARG_LIST,
            ],
            "Encoded graffiti exceeds the maximum length of 32 bytes",
            {},
            [],
            id="--graffiti invalid input - too long",
        ),
        pytest.param(
            ["--gas-limit=1000000", *MINIMUM_ARG_LIST],
            None,
            {"gas_limit": 1_000_000},
            ["gas_limit: 1000000"],
            id="--gas-limit valid input",
        ),
        pytest.param(
            [
                "--network=mainnet",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            None,
            {"gas_limit": 60_000_000},
            [],
            id="--gas-limit default value Ethereum Mainnet",
        ),
        pytest.param(
            [
                "--network=gnosis",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            None,
            {"gas_limit": 17_000_000},
            [],
            id="--gas-limit default value Gnosis Chain",
        ),
        pytest.param(
            [
                "--network=hoodi",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            None,
            {"gas_limit": 60_000_000},
            [],
            id="--gas-limit default value Hoodi testnet",
        ),
        pytest.param(
            [
                "--network=chiado",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            None,
            {"gas_limit": 17_000_000},
            [],
            id="--gas-limit default value Chiado testnet",
        ),
        pytest.param(
            ["--gas-limit=two", *MINIMUM_ARG_LIST],
            "--gas-limit: invalid int value: 'two'",
            {},
            [],
            id="--gas-limit invalid input - not a number",
        ),
        pytest.param(
            [
                "--network=custom",
                "--network-custom-config-path=/path/to/config.yaml",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            None,
            {
                "network": Network.CUSTOM,
                "network_custom_config_path": "/path/to/config.yaml",
            },
            [
                "network: Network.CUSTOM",
                "network_custom_config_path: /path/to/config.yaml",
            ],
            id="--network-custom-config-path",
        ),
        pytest.param(
            [
                "--network=mainnet",
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
                "--enable-keymanager-api",
            ],
            "argument --enable-keymanager-api: not allowed with argument --remote-signer-url",
            {},
            [],
            id="Mutually exclusive group - key source",
        ),
        pytest.param(
            [
                "--network=mainnet",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
                "--enable-keymanager-api",
            ],
            None,
            {
                "enable_keymanager_api": True,
                "keymanager_api_token_file_path": Path(
                    "/vero/data/keymanager-api-token.txt"
                ),
            },
            [
                "enable_keymanager_api: True",
                "keymanager_api_token_file_path: /vero/data/keymanager-api-token.txt",
            ],
            id="--enable-keymanager-api (no --remote-signer-url)",
        ),
        pytest.param(
            ["--log-level=DEBUG", *MINIMUM_ARG_LIST],
            None,
            {
                "log_level": logging.DEBUG,
            },
            [
                "log_level: DEBUG",
            ],
            id="--log-level override",
        ),
    ],
)
def test_parse_cli_args(
    list_of_args: list[str],
    expected_error_message: str | None,
    expected_attr_values: dict[str, Any],
    expected_log_messages: list[str],
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture,  # type: ignore[type-arg]
) -> None:
    if expected_error_message:
        with pytest.raises(SystemExit):
            parse_cli_args(list_of_args)
        captured = capsys.readouterr()
        assert expected_error_message in captured.err
    else:
        parsed_args = parse_cli_args(list_of_args)
        for attr_name, attr_value in expected_attr_values.items():
            assert getattr(parsed_args, attr_name) == attr_value

    for log_message in expected_log_messages:
        assert log_message in caplog.messages


def test_parse_cli_args_full_set() -> None:
    list_of_args = [
        "--network=custom",
        "--network-custom-config-path=/path/to/config.yaml",
        "--remote-signer-url=http://signer:9000",
        "--beacon-node-urls=http://beacon-node:5052",
        "--beacon-node-urls-proposal=http://beacon-node-prop:5052",
        "--attestation-consensus-threshold=1",
        "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
        "--data-dir=/tmp/vero",
        "--graffiti=test-graffiti",
        "--gas-limit=31000000",
        "--use-external-builder",
        "--builder-boost-factor=80",
        "--enable-doppelganger-detection",
        "--keymanager-api-token-file-path=/tmp/vero/token.txt",
        "--keymanager-api-address=3.3.3.3",
        "--keymanager-api-port=3333",
        "--metrics-address=1.2.3.4",
        "--metrics-port=4321",
        "--log-level=DEBUG",
        "--ignore-spec-mismatch",
        "----DANGER----disable-slashing-detection",
    ]
    expected_attr_values = {
        "network": Network.CUSTOM,
        "network_custom_config_path": "/path/to/config.yaml",
        "remote_signer_url": "http://signer:9000",
        "beacon_node_urls": ["http://beacon-node:5052"],
        "beacon_node_urls_proposal": ["http://beacon-node-prop:5052"],
        "attestation_consensus_threshold": 1,
        "fee_recipient": "0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
        "data_dir": "/tmp/vero",
        "graffiti": b"test-graffiti".ljust(32, b"\x00"),
        "gas_limit": 31_000_000,
        "use_external_builder": True,
        "builder_boost_factor": 80,
        "enable_doppelganger_detection": True,
        "enable_keymanager_api": False,
        "keymanager_api_token_file_path": Path("/tmp/vero/token.txt"),
        "keymanager_api_address": "3.3.3.3",
        "keymanager_api_port": 3333,
        "metrics_address": "1.2.3.4",
        "metrics_port": 4321,
        "log_level": logging.DEBUG,
        "ignore_spec_mismatch": True,
        "disable_slashing_detection": True,
    }

    # Ensure the list is not missing any possible arguments
    arg_names = []
    for arg in list_of_args:
        if "=" in arg:
            arg_name, _ = arg.split("=", 1)
            arg_names.append(arg_name)
        else:
            arg_names.append(arg)

    parsed_args = parse_cli_args(list_of_args)

    for action in get_parser()._actions:
        # Ignoring missing --enable-keymanager-api flag since it's
        # mutually exclusive with --remote-signer-url
        if action.dest in ("help", "enable_keymanager_api"):
            continue

        assert all(os in arg_names for os in action.option_strings), (
            f"Missing flag: {action.option_strings}"
        )

        dest_attribute = action.dest.removeprefix("DANGER____")
        assert (
            getattr(parsed_args, dest_attribute) == expected_attr_values[dest_attribute]
        )


def test_parse_cli_args_minimal_set_with_defaults() -> None:
    list_of_args = [
        "--network=mainnet",
        "--remote-signer-url=http://signer:9000",
        "--beacon-node-urls=http://beacon-node:5052",
        "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
    ]
    expected_result = CLIArgs(
        network=Network.MAINNET,
        network_custom_config_path=None,
        remote_signer_url="http://signer:9000",
        beacon_node_urls=["http://beacon-node:5052"],
        beacon_node_urls_proposal=[],
        attestation_consensus_threshold=1,
        fee_recipient="0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
        data_dir="/vero/data",
        graffiti=encode_graffiti("Vero v0.0.0-dev"),
        gas_limit=60_000_000,
        use_external_builder=False,
        builder_boost_factor=90,
        enable_doppelganger_detection=False,
        enable_keymanager_api=False,
        keymanager_api_token_file_path=Path("/vero/data") / "keymanager-api-token.txt",
        keymanager_api_address="localhost",
        keymanager_api_port=8001,
        metrics_address="localhost",
        metrics_port=8000,
        log_level=logging.INFO,
        ignore_spec_mismatch=False,
        disable_slashing_detection=False,
    )

    parsed = parse_cli_args(list_of_args)
    for attr_name in dir(expected_result):
        if attr_name.startswith("__"):
            continue
        assert getattr(parsed, attr_name) == getattr(expected_result, attr_name)
    assert parsed == expected_result
