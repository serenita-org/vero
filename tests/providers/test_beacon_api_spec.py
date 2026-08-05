import ast
import os
from pathlib import Path

import pytest

from tests.beacon_api_spec import BeaconAPISpec

_SPEC_PATH_ENV = "BEACON_API_SPEC_PATH"

# These requests intentionally bypass BeaconNode._make_request: genesis uses a
# temporary session during startup, while events keeps an SSE connection open.
_DIRECT_SESSION_OPERATIONS = {
    ("GET", "/eth/v1/beacon/genesis"),
    ("GET", "/eth/v1/events"),
}


@pytest.fixture(scope="module")
def beacon_api_spec() -> BeaconAPISpec:
    spec_path = os.environ.get(_SPEC_PATH_ENV)
    if spec_path is None:
        pytest.skip(f"{_SPEC_PATH_ENV} is not set")
    assert spec_path is not None
    return BeaconAPISpec(Path(spec_path))


def _make_request_operations(tree: ast.AST) -> set[tuple[str, str]]:
    operations: set[tuple[str, str]] = set()
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        if (
            not isinstance(call.func, ast.Attribute)
            or call.func.attr != "_make_request"
        ):
            continue

        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        method = ast.literal_eval(keywords["method"])
        path = ast.literal_eval(keywords["endpoint"])
        operations.add((method, path))

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
    beacon_api_spec: BeaconAPISpec,
) -> None:
    for method, path in _provider_operations():
        beacon_api_spec.operation_for(method, path)
