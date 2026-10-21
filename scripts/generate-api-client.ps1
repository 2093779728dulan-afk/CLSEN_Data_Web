#Requires -Version 7.0

[CmdletBinding()]
param(
    [string] $PythonExecutable,
    [string] $OutputPath,
    [switch] $Check
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = [System.IO.Path]::GetFullPath(
    (Join-Path -Path $PSScriptRoot -ChildPath "..")
)

if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $PythonExecutable = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path -LiteralPath $PythonExecutable -PathType Leaf)) {
    throw "Python executable was not found: $PythonExecutable"
}

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $resolvedOutputPath = Join-Path $repositoryRoot "frontend\src\api\generated.ts"
}
elseif ([System.IO.Path]::IsPathRooted($OutputPath)) {
    $resolvedOutputPath = [System.IO.Path]::GetFullPath($OutputPath)
}
else {
    $resolvedOutputPath = [System.IO.Path]::GetFullPath(
        (Join-Path $repositoryRoot $OutputPath)
    )
}

$generator = @'
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

HTTP_METHODS = ("delete", "get", "patch", "post", "put")
SUCCESS_STATUSES = "200 | 201 | 202 | 203 | 204 | 205 | 206 | 207 | 208 | 226"


def quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def unique(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(items))


def union_type(items: Sequence[str]) -> str:
    members = unique(items)
    if "unknown" in members:
        return "unknown"
    return " | ".join(members) or "never"


def literal_type(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return quote(value)
    return json.dumps(value, ensure_ascii=False)


def reference_type(reference: str) -> str:
    name = reference.rsplit("/", maxsplit=1)[-1]
    return f'components["schemas"][{quote(name)}]'


def schema_type(value: object) -> str:
    if not isinstance(value, Mapping):
        return "unknown"
    schema = cast(Mapping[str, Any], value)

    reference = schema.get("$ref")
    if isinstance(reference, str):
        result = reference_type(reference)
    elif "const" in schema:
        result = literal_type(schema["const"])
    elif isinstance(schema.get("enum"), list):
        values = cast(list[object], schema["enum"])
        result = " | ".join(unique([literal_type(item) for item in values]))
    elif isinstance(schema.get("allOf"), list):
        members = cast(list[object], schema["allOf"])
        result = " & ".join(f"({schema_type(member)})" for member in members)
    elif isinstance(schema.get("oneOf"), list):
        members = cast(list[object], schema["oneOf"])
        result = union_type([schema_type(member) for member in members])
    elif isinstance(schema.get("anyOf"), list):
        members = cast(list[object], schema["anyOf"])
        result = union_type([schema_type(member) for member in members])
    else:
        declared_type = schema.get("type")
        if isinstance(declared_type, list):
            result = union_type(
                [
                    schema_type({**schema, "type": member})
                    for member in declared_type
                ]
            )
        elif declared_type == "null":
            result = "null"
        elif declared_type == "boolean":
            result = "boolean"
        elif declared_type in {"integer", "number"}:
            result = "number"
        elif declared_type == "string":
            result = "Blob" if schema.get("format") == "binary" else "string"
        elif declared_type == "array":
            result = f"Array<{schema_type(schema.get('items'))}>"
        elif declared_type == "object" or "properties" in schema:
            properties = schema.get("properties", {})
            required_value = schema.get("required", [])
            required = set(required_value) if isinstance(required_value, list) else set()
            fields: list[str] = []
            if isinstance(properties, Mapping):
                for name in sorted(properties):
                    optional = "" if name in required else "?"
                    fields.append(
                        f"{quote(str(name))}{optional}: "
                        f"{schema_type(properties[name])};"
                    )
            object_type = "{ " + " ".join(fields) + " }"
            additional = schema.get("additionalProperties")
            if isinstance(additional, Mapping):
                dictionary_type = f"Record<string, {schema_type(additional)}>"
                result = (
                    f"({object_type} & {dictionary_type})"
                    if fields
                    else dictionary_type
                )
            elif additional is True:
                result = (
                    f"({object_type} & Record<string, unknown>)"
                    if fields
                    else "Record<string, unknown>"
                )
            elif fields:
                result = object_type
            elif additional is False:
                result = "Record<string, never>"
            else:
                result = "Record<string, unknown>"
        else:
            result = "unknown"

    if (
        schema.get("nullable") is True
        and result != "unknown"
        and "null" not in result.split(" | ")
    ):
        return f"{result} | null"
    return result or "never"


def content_schema(content: object) -> object | None:
    if not isinstance(content, Mapping) or not content:
        return None
    media_types = (
        "application/json",
        "text/csv",
        "application/octet-stream",
        "*/*",
    )
    selected: object | None = None
    for media_type in media_types:
        if media_type in content:
            selected = content[media_type]
            break
    if selected is None:
        selected = content[sorted(str(key) for key in content)[0]]
    if not isinstance(selected, Mapping):
        return None
    return selected.get("schema")


def parameter_object(parameters: object, location: str) -> str:
    if not isinstance(parameters, list):
        return "Record<string, never>"
    fields: list[str] = []
    for parameter_value in parameters:
        if not isinstance(parameter_value, Mapping):
            continue
        parameter = cast(Mapping[str, Any], parameter_value)
        if parameter.get("in") != location or not isinstance(parameter.get("name"), str):
            continue
        name = cast(str, parameter["name"])
        optional = "" if parameter.get("required") is True else "?"
        fields.append(
            f"{quote(name)}{optional}: {schema_type(parameter.get('schema'))};"
        )
    return "{ " + " ".join(fields) + " }" if fields else "Record<string, never>"


def request_body_type(operation: Mapping[str, Any]) -> str:
    request_body = operation.get("requestBody")
    if not isinstance(request_body, Mapping):
        return "never"
    value = schema_type(content_schema(request_body.get("content")))
    return value if request_body.get("required") is True else f"{value} | undefined"


def response_type(response: object, status_code: str) -> str:
    if not isinstance(response, Mapping):
        return "unknown"
    schema = content_schema(response.get("content"))
    if schema is None:
        return "void" if status_code == "204" else "unknown"
    return schema_type(schema)


def security_type(operation: Mapping[str, Any]) -> str:
    security = operation.get("security")
    names: list[str] = []
    if isinstance(security, list):
        for requirement in security:
            if isinstance(requirement, Mapping):
                names.extend(str(name) for name in requirement)
    return " | ".join(quote(name) for name in sorted(set(names))) or '"public"'


def operations(openapi: Mapping[str, Any]) -> list[tuple[str, str, str, Mapping[str, Any]]]:
    result: list[tuple[str, str, str, Mapping[str, Any]]] = []
    paths = openapi.get("paths", {})
    if not isinstance(paths, Mapping):
        return result
    for path in sorted(str(item) for item in paths):
        path_item = paths[path]
        if not isinstance(path_item, Mapping):
            continue
        inherited_parameters = path_item.get("parameters", [])
        for method in HTTP_METHODS:
            operation_value = path_item.get(method)
            if not isinstance(operation_value, Mapping):
                continue
            operation = dict(cast(Mapping[str, Any], operation_value))
            own_parameters = operation.get("parameters", [])
            operation["parameters"] = [
                *(inherited_parameters if isinstance(inherited_parameters, list) else []),
                *(own_parameters if isinstance(own_parameters, list) else []),
            ]
            operation_id = operation.get("operationId")
            if not isinstance(operation_id, str) or not operation_id:
                raise ValueError(f"OpenAPI operation is missing operationId: {method} {path}")
            result.append((operation_id, method, path, operation))
    operation_ids = [item[0] for item in result]
    if len(operation_ids) != len(set(operation_ids)):
        raise ValueError("OpenAPI operationId values must be unique")
    return result


def render(openapi: Mapping[str, Any], digest: str) -> str:
    operation_items = operations(openapi)
    components_value = openapi.get("components", {})
    components = (
        cast(Mapping[str, Any], components_value)
        if isinstance(components_value, Mapping)
        else {}
    )
    schemas_value = components.get("schemas", {})
    schemas = (
        cast(Mapping[str, Any], schemas_value)
        if isinstance(schemas_value, Mapping)
        else {}
    )

    lines = [
        "/**",
        " * Generated from FastAPI OpenAPI. Do not edit by hand.",
        " * Run: pwsh ./scripts/generate-api-client.ps1",
        " */",
        f"// OpenAPI SHA-256: {digest}",
        "",
        "export interface components {",
        "  schemas: {",
    ]
    for name in sorted(str(item) for item in schemas):
        lines.append(f"    {quote(name)}: {schema_type(schemas[name])};")
    lines.extend(["  };", "}", ""])

    for name in sorted(str(item) for item in schemas):
        if name.isidentifier():
            lines.append(
                f"export type {name} = components[\"schemas\"][{quote(name)}];"
            )
    lines.extend(["", "export const API_OPERATIONS = {"])
    for operation_id, method, path, _operation in operation_items:
        lines.append(
            f"  {quote(operation_id)}: {{ method: {quote(method.upper())}, "
            f"path: {quote(path)} }},"
        )
    lines.extend(["} as const;", "", "export interface operations {"])

    for operation_id, _method, _path, operation in operation_items:
        parameters = operation.get("parameters")
        lines.extend(
            [
                f"  {quote(operation_id)}: {{",
                f"    security: {security_type(operation)};",
                f"    path: {parameter_object(parameters, 'path')};",
                f"    query: {parameter_object(parameters, 'query')};",
                f"    headers: {parameter_object(parameters, 'header')};",
                f"    requestBody: {request_body_type(operation)};",
                "    responses: {",
            ]
        )
        responses = operation.get("responses", {})
        if isinstance(responses, Mapping):
            for status_code in sorted(str(item) for item in responses):
                key = status_code if status_code.isdigit() else quote(status_code)
                lines.append(
                    f"      {key}: {response_type(responses[status_code], status_code)};"
                )
        lines.extend(["    };", "  };"])
    lines.extend(
        [
            "}",
            "",
            "export type ApiOperationId = keyof operations;",
            "export type ApiPath<Id extends ApiOperationId> = operations[Id][\"path\"];",
            "export type ApiQuery<Id extends ApiOperationId> = operations[Id][\"query\"];",
            "export type ApiHeaders<Id extends ApiOperationId> = operations[Id][\"headers\"];",
            "export type ApiRequestBody<Id extends ApiOperationId> = operations[Id][\"requestBody\"];",
            "export type ApiResponse<",
            "  Id extends ApiOperationId,",
            "  Status extends keyof operations[Id][\"responses\"],",
            "> = operations[Id][\"responses\"][Status];",
            "export type ApiSuccessResponse<Id extends ApiOperationId> = ApiResponse<",
            "  Id,",
            f"  Extract<keyof operations[Id][\"responses\"], {SUCCESS_STATUSES}>",
            ">;",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()

    backend_root = arguments.repo_root / "backend"
    sys.path.insert(0, str(backend_root))
    from app.config import Settings
    from app.main import create_app

    settings = Settings(
        environment="test",
        log_level="CRITICAL",
        cors_allowed_origins=(),
        session_secret="openapi-generation-only-secret-000000",
        session_cookie_secure=False,
    )
    openapi = cast(Mapping[str, Any], create_app(settings=settings).openapi())
    canonical = json.dumps(
        openapi,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    generated = render(openapi, digest)

    output = arguments.output.resolve()
    if arguments.check:
        if not output.is_file() or output.read_text(encoding="utf-8") != generated:
            print(
                "Generated API contract is stale. Run "
                "pwsh ./scripts/generate-api-client.ps1.",
                file=sys.stderr,
            )
            return 1
        print(f"Generated API contract is current: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generated, encoding="utf-8", newline="\n")
    print(f"Generated API contract: {output}")
    return 0


raise SystemExit(main())
'@

$generatorArguments = @(
    "-",
    "--repo-root",
    $repositoryRoot,
    "--output",
    $resolvedOutputPath
)
if ($Check) {
    $generatorArguments += "--check"
}

$generator | & $PythonExecutable @generatorArguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
