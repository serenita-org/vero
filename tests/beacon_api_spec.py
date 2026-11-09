import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import msgspec
from aiohttp.hdrs import CONTENT_TYPE
from jsonschema import Draft202012Validator, FormatChecker
from yarl import URL

from providers._headers import ContentType


def _validate(schema: Mapping[str, Any], value: object) -> None:
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def _validate_content(
    content: Mapping[str, Any], headers: Mapping[str, str], body: str | bytes
) -> None:
    name = CONTENT_TYPE.lower()
    assert name in headers, f"Missing {CONTENT_TYPE} header"
    media_type = headers[name].split(";", maxsplit=1)[0]
    assert media_type in content, (
        f"{media_type} is not one of the declared content types {tuple(content)}"
    )
    if media_type == ContentType.JSON.value:
        _validate(content[media_type]["schema"], msgspec.json.decode(body))


def _validate_parameters(
    operation: Mapping[str, Any], location: str, values: Mapping[str, object]
) -> None:
    parameters = [
        parameter
        for parameter in operation.get("parameters", [])
        if parameter["in"] == location
    ]

    def key(parameter: Mapping[str, Any]) -> str:
        name: str = parameter["name"]
        return name.lower() if location == "header" else name

    normalized_values = dict(values)
    for parameter in parameters:
        parameter_key = key(parameter)
        value = normalized_values.get(parameter_key)
        if (
            parameter["schema"].get("type") == "boolean"
            and isinstance(value, str)
            and value.lower() in ("true", "false")
        ):
            normalized_values[parameter_key] = value.lower() == "true"

    _validate(
        {
            "type": "object",
            "properties": {
                key(parameter): parameter["schema"] for parameter in parameters
            },
            "required": [
                key(parameter)
                for parameter in parameters
                if parameter.get("required", False)
            ],
            "additionalProperties": location == "header",
        },
        normalized_values,
    )


def _query_parameter_value(parameter: Mapping[str, Any], url: URL) -> object:
    name = parameter["name"]
    schema = parameter["schema"]
    if schema.get("type") == "array":
        return list(url.query.getall(name))

    value = url.query[name]
    if schema.get("type") == "boolean" and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return value


def _validate_response_headers(
    definitions: Mapping[str, Any], values: Mapping[str, str]
) -> None:
    for name, definition in definitions.items():
        value: str | bool | None = values.get(name.lower())
        if definition.get("required", False):
            assert value is not None, f"Missing required response header {name}"
        if value is None:
            continue

        schema = definition["schema"]
        if (
            schema.get("type") == "boolean"
            and isinstance(value, str)
            and value.lower() in ("true", "false")
        ):
            value = value.lower() == "true"
        _validate(schema, value)


class BeaconAPISpec:
    def __init__(self, path: Path) -> None:
        with path.open("rb") as spec_file:
            self.spec: dict[str, Any] = json.load(spec_file)
        assert self.spec["openapi"].startswith("3.1."), self.spec["openapi"]

    def operation_for(
        self, method: str, path: str
    ) -> tuple[Mapping[str, Any], dict[str, str]]:
        for spec_path, path_item in self.spec["paths"].items():
            operation = path_item.get(method.lower())
            if operation is None:
                continue

            names = re.findall(r"{([^}]+)}", spec_path)
            match = re.fullmatch(re.sub(r"{[^}]+}", r"([^/]+)", spec_path), path)
            if match is not None:
                return operation, dict(zip(names, match.groups(), strict=True))

        raise AssertionError(f"No Beacon API operation for {method} {path}")

    def validate_request(
        self, method: str, url: URL, request: Mapping[str, Any]
    ) -> None:
        operation, path_parameters = self.operation_for(method, url.path)
        request_headers: Mapping[str, str] = request["headers"]
        headers = {name.lower(): value for name, value in request_headers.items()}
        query: dict[str, object] = {}

        for parameter in operation.get("parameters", []):
            name = parameter["name"]
            if parameter["in"] == "query" and name in url.query:
                query[name] = _query_parameter_value(parameter, url)

        for location, values in (
            ("path", dict(path_parameters)),
            ("query", query),
            ("header", headers),
        ):
            _validate_parameters(operation, location, values)

        request_body = operation.get("requestBody")
        data = request.get("data")
        if request_body is None:
            assert data is None
            return

        assert data is not None
        _validate_content(request_body["content"], headers, data)

    def validate_response(
        self,
        method: str,
        url: URL,
        *,
        status: int,
        headers: Mapping[str, str],
        body: str | bytes,
    ) -> None:
        operation, _ = self.operation_for(method, url.path)
        response = operation["responses"].get(str(status))
        assert response is not None, f"Unexpected response status {status}"

        response_headers = {name.lower(): value for name, value in headers.items()}
        _validate_response_headers(response.get("headers", {}), response_headers)

        content = response.get("content")
        if content is None:
            assert body in ("", b"")
            return

        _validate_content(content, response_headers, body)
