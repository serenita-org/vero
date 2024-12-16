from typing import Any

import pytest

from args import parse_cli_args


@pytest.mark.parametrize(
    argnames=[
        "list_of_args",
        "expected_error_message",
        "expected_attr_values",
    ],
    argvalues=[
        pytest.param(
            [],
            "the following arguments are required: --remote-signer-url, --beacon-node-urls, --fee-recipient",
            {},
            id="No arguments provided",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            None,
            {
                "remote_signer_url": "http://signer:9000",
                "beacon_node_urls": ["http://beacon-node:5052"],
                "beacon_node_urls_proposal": [],
                "attestation_consensus_threshold": 1,
                "fee_recipient": "0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            },
            id="Minimal valid list of arguments",
        ),
        pytest.param(
            [
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
                "--metrics-address=1.2.3.4",
                "--metrics-port=4321",
                "--metrics-multiprocess-mode",
                "--log-level=DEBUG",
            ],
            None,
            {
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
                "metrics_address": "1.2.3.4",
                "metrics_port": 4321,
                "metrics_multiprocess_mode": True,
                "log_level": "DEBUG",
            },
            id="Full valid list of arguments",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node-1:5052,http://beacon-node-2:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            None,
            {
                "remote_signer_url": "http://signer:9000",
                "beacon_node_urls": [
                    "http://beacon-node-1:5052",
                    "http://beacon-node-2:5052",
                ],
                "fee_recipient": "0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            },
            id="--beacon-node-urls valid input - multiple values",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=   ",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "Not enough beacon node urls provided",
            {},
            id="--beacon-node-urls invalid input - empty string",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node-1:5052,http://beacon-node-2:5052,http://beacon-node-1:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "beacon node urls must be unique",
            {},
            id="--beacon-node-urls invalid input - duplicate values",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--beacon-node-urls-proposal=http://beacon-node-prop:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            None,
            {
                "beacon_node_urls": ["http://beacon-node:5052"],
                "beacon_node_urls_proposal": ["http://beacon-node-prop:5052"],
            },
            id="--beacon-node-urls-proposal",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--attestation-consensus-threshold=asd",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "argument --attestation-consensus-threshold: invalid int value",
            {},
            id="--attestation-consensus-threshold invalid input - string instead of int",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--attestation-consensus-threshold=2",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "Invalid value for attestation_consensus_threshold (2) with 1 beacon node(s)",
            {},
            id="--attestation-consensus-threshold invalid input - threshold impossible to reach",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--attestation-consensus-threshold=0",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "Invalid value for attestation_consensus_threshold: 0",
            {},
            id="--attestation-consensus-threshold invalid input - 0",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c",
            ],
            "Invalid fee recipient: 0x1c6c",
            {},
            id="--fee-recipient invalid input - wrong length",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "Invalid fee recipient: 1c6c9654",
            {},
            id="--fee-recipient invalid input - no 0x prefix",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0xGGGG96549debfc6aaec7631051b84ce9a6e11ad2",
            ],
            "Invalid fee recipient 0xGGGG96549debfc6aaec7631051b84ce9a6e11ad2: ValueError('non-hexadecimal number found",
            {},
            id="--fee-recipient invalid input - non-hex character",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
                "--data-dir=data",
            ],
            None,
            {"data_dir": "data"},
            id="--data-dir - relative path",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
                "--data-dir=/tmp/data",
            ],
            None,
            {"data_dir": "/tmp/data"},
            id="--data-dir - absolute path",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
                "--graffiti=short",
            ],
            None,
            {"graffiti": b"short".ljust(32, b"\x00")},
            id="--graffiti valid input",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
                "--graffiti=🐟 💰 ❓",
            ],
            None,
            {"graffiti": "🐟 💰 ❓".encode().ljust(32, b"\x00")},
            id="--graffiti valid input - emoji",
        ),
        pytest.param(
            [
                "--remote-signer-url=http://signer:9000",
                "--beacon-node-urls=http://beacon-node:5052",
                "--fee-recipient=0x1c6c96549debfc6aaec7631051b84ce9a6e11ad2",
                "--graffiti=waaaaaaaay_toooooo_loooooooooooooooooong",
            ],
            "Encoded graffiti exceeds the maximum length of 32 bytes",
            {},
            id="--graffiti invalid input - too long",
        ),
    ],
)
def test_parse_cli_args(
    list_of_args: list[str],
    expected_error_message: str | None,
    expected_attr_values: dict[str, Any],
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
