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

_JSON = ContentType.JSON.value


def _validate(schema: Mapping[str, Any], value: object) -> None:
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(value)


def _wire_value(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return [_wire_value(item) for item in value]
    return value if isinstance(value, bool) else str(value)


def _headers(
    values: Mapping[str, object] | None, *, wire_values: bool = False
) -> dict[str, object]:
    return {
        name.lower(): _wire_value(value) if wire_values else value
        for name, value in (values or {}).items()
    }


def _media_type(headers: Mapping[str, object], default: str) -> str:
    return str(headers.get(CONTENT_TYPE.lower(), default)).split(";", maxsplit=1)[0]


def _validate_content(
    content: Mapping[str, Any], media_type: str, value: object
) -> None:
    assert media_type in content, (
        f"{media_type} is not one of the declared content types {tuple(content)}"
    )
    if media_type == _JSON:
        _validate(content[media_type]["schema"], value)


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
        values,
    )


def _validate_response_headers(
    definitions: Mapping[str, Any], values: Mapping[str, object]
) -> None:
    for name, definition in definitions.items():
        value = values.get(name.lower())
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
        headers = _headers(request.get("headers"), wire_values=True)
        query: dict[str, object] = {}

        for parameter in operation.get("parameters", []):
            name = parameter["name"]
            if parameter["in"] == "query" and name in url.query:
                query[name] = (
                    list(url.query.getall(name))
                    if parameter["schema"].get("type") == "array"
                    else url.query[name]
                )

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
        media_type = _media_type(headers, _JSON)
        value = msgspec.json.decode(data) if media_type == _JSON else data
        _validate_content(request_body["content"], media_type, value)

    def validate_response(
        self,
        method: str,
        url: URL,
        *,
        status: int,
        headers: Mapping[str, object] | None,
        content_type: str,
        body: str | bytes,
        payload: object | None,
    ) -> None:
        operation, _ = self.operation_for(method, url.path)
        response = operation["responses"].get(str(status))
        assert response is not None, f"Unexpected response status {status}"

        response_headers = _headers(headers)
        _validate_response_headers(response.get("headers", {}), response_headers)

        content = response.get("content")
        if content is None:
            assert payload is None
            assert body in ("", b"")
            return

        media_type = _media_type(response_headers, content_type)
        value = (
            payload
            if payload is not None
            else msgspec.json.decode(body)
            if media_type == _JSON
            else body
        )
        _validate_content(content, media_type, value)
