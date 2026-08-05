import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import msgspec
from jsonschema import Draft202012Validator, FormatChecker
from yarl import URL

from providers._headers import ContentType


class BeaconAPISpec:
    def __init__(self, path: Path) -> None:
        with path.open("rb") as spec_file:
            self.spec: dict[str, Any] = json.load(spec_file)

        assert self.spec["openapi"].startswith("3.1."), self.spec["openapi"]
        self.seen_operation_ids: set[str] = set()

    def operation_for(
        self, method: str, path: str
    ) -> tuple[str, Mapping[str, Any], dict[str, str]]:
        for spec_path, path_item in self.spec["paths"].items():
            operation = path_item.get(method.lower())
            if operation is None:
                continue

            parameter_names = re.findall(r"{([^}]+)}", spec_path)
            pattern = re.sub(r"{[^}]+}", r"([^/]+)", spec_path)
            match = re.fullmatch(pattern, path)
            if match is not None:
                return (
                    operation["operationId"],
                    operation,
                    dict(zip(parameter_names, match.groups(), strict=True)),
                )

        raise AssertionError(f"No Beacon API operation for {method} {path}")

    def validate_request(
        self, method: str, url: URL, request: Mapping[str, Any]
    ) -> None:
        operation_id, operation, path_parameters = self.operation_for(method, url.path)
        self.seen_operation_ids.add(operation_id)

        headers = {
            name.lower(): self._wire_value(value)
            for name, value in (request.get("headers") or {}).items()
        }
        values_by_location: dict[str, dict[str, object]] = {
            "path": dict(path_parameters),
            "query": {},
            "header": headers,
        }

        for parameter in operation.get("parameters", []):
            if parameter["in"] != "query" or parameter["name"] not in url.query:
                continue
            name = parameter["name"]
            if parameter["schema"].get("type") == "array":
                values_by_location["query"][name] = list(url.query.getall(name))
            else:
                values_by_location["query"][name] = url.query[name]

        for location, values in values_by_location.items():
            parameters = [
                parameter
                for parameter in operation.get("parameters", [])
                if parameter["in"] == location
            ]
            properties = {
                parameter["name"].lower()
                if location == "header"
                else parameter["name"]: parameter["schema"]
                for parameter in parameters
            }
            required = [
                parameter["name"].lower() if location == "header" else parameter["name"]
                for parameter in parameters
                if parameter.get("required", False)
            ]
            Draft202012Validator(
                {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": location == "header",
                },
                format_checker=FormatChecker(),
            ).validate(values)

        self._validate_body(operation, request, headers)

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
        _, operation, _ = self.operation_for(method, url.path)
        response = operation["responses"].get(str(status))
        assert response is not None, f"Unexpected response status {status}"

        response_headers = {
            name.lower(): value for name, value in (headers or {}).items()
        }
        for name, header in response.get("headers", {}).items():
            value = response_headers.get(name.lower())
            if header.get("required", False):
                assert value is not None, f"Missing required response header {name}"
            if value is not None:
                schema = header["schema"]
                if schema.get("type") == "boolean" and isinstance(value, str):
                    value = value.lower() == "true"
                Draft202012Validator(schema).validate(value)

        content = response.get("content")
        if content is None:
            assert payload is None
            assert body in ("", b"")
            return

        media_type = str(response_headers.get("content-type", content_type)).split(
            ";", maxsplit=1
        )[0]
        assert media_type in content, (
            f"{media_type} is not one of the response content types {tuple(content)}"
        )
        if media_type == ContentType.JSON.value:
            instance = payload if payload is not None else msgspec.json.decode(body)
            Draft202012Validator(
                content[media_type]["schema"], format_checker=FormatChecker()
            ).validate(instance)

    @staticmethod
    def _validate_body(
        operation: Mapping[str, Any],
        request: Mapping[str, Any],
        headers: Mapping[str, object],
    ) -> None:
        request_body = operation.get("requestBody")
        data = request.get("data")
        if request_body is None:
            assert data is None
            return

        assert data is not None
        content_type = str(headers.get("content-type", ContentType.JSON.value)).split(
            ";", maxsplit=1
        )[0]
        content = request_body["content"]
        assert content_type in content, (
            f"{content_type} is not one of the request content types {tuple(content)}"
        )

        if content_type == ContentType.JSON.value:
            Draft202012Validator(
                content[content_type]["schema"], format_checker=FormatChecker()
            ).validate(msgspec.json.decode(data))

    @staticmethod
    def _wire_value(value: object) -> object:
        if isinstance(value, (list, tuple)):
            return [BeaconAPISpec._wire_value(item) for item in value]
        if isinstance(value, bool):
            return value
        return str(value)
