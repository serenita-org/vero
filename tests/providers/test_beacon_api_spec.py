import ast
from pathlib import Path

import pytest

from tests.beacon_api_spec import BeaconAPISpec, _headers, _validate_parameters

# These requests intentionally bypass BeaconNode._make_request: genesis uses a
# temporary session during startup, while events keeps an SSE connection open.
_DIRECT_SESSION_OPERATIONS = {
    ("GET", "/eth/v1/beacon/genesis"),
    ("GET", "/eth/v1/events"),
}


# The AST helper cannot evaluate endpoints assembled dynamically. Map each
# (provider function name, endpoint variable name) to the set of all possible
# endpoint strings, keeping placeholders such as {slot} unformatted. For another
# dynamic endpoint, add its function/variable pair and every path it can produce;
# the helper combines each path with the method from the _make_request call.
_DYNAMIC_ENDPOINTS = {
    ("produce_block_v4", "_endpoint"): {
        "/eth/v4/validator/blocks/{slot}",
        "/eth/v4/validator/blocks/{slot}/with_bid",
    },
}


def _make_request_operations(tree: ast.AST) -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in (node for node in ast.walk(function) if isinstance(node, ast.Call)):
            if (
                not isinstance(call.func, ast.Attribute)
                or call.func.attr != "_make_request"
            ):
                continue

            keywords = {keyword.arg: keyword.value for keyword in call.keywords}
            method = ast.literal_eval(keywords["method"])
            endpoint = keywords["endpoint"]
            if isinstance(endpoint, ast.Name):
                paths = _DYNAMIC_ENDPOINTS[(function.name, endpoint.id)]
            else:
                paths = {ast.literal_eval(endpoint)}
            operations.update((method, path) for path in paths)

    return operations


def _provider_operations() -> set[tuple[str, str]]:
    root = Path(__file__).parents[2]
    operations = set(_DIRECT_SESSION_OPERATIONS)

    for source_path in (
        root / "src/providers/beacon_node.py",
        root / "src/providers/vero.py",
    ):
        tree = ast.parse(source_path.read_text())
        operations.update(_make_request_operations(tree))

    return operations


def test_all_provider_operations_exist_in_spec(
    beacon_api_spec: BeaconAPISpec | None,
) -> None:
    if beacon_api_spec is None:
        pytest.skip("--beacon-api-spec-path is not provided")

    for method, path in _provider_operations():
        beacon_api_spec.operation_for(method, path)


@pytest.mark.parametrize("value", ["true", "false"])
def test_boolean_header_wire_value(value: str) -> None:
    operation = {
        "parameters": [
            {
                "name": "Example-Boolean",
                "in": "header",
                "required": True,
                "schema": {"type": "boolean"},
            }
        ]
    }

    _validate_parameters(
        operation,
        "header",
        {"example-boolean": value},
    )


@pytest.mark.parametrize("value", [True, False])
def test_boolean_header_rejects_unserialized_value(value: bool) -> None:
    with pytest.raises(
        TypeError,
        match="HTTP header values must be serialized strings, not booleans",
    ):
        _headers({"Example-Boolean": value}, wire_values=True)


def test_provider_operations_includes_dynamic_endpoints() -> None:
    assert {
        ("POST", "/eth/v4/validator/blocks/{slot}"),
        ("POST", "/eth/v4/validator/blocks/{slot}/with_bid"),
    } <= _provider_operations()
