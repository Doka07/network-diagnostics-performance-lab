"""Local JSON Schema validation with explicit types and no remote references."""

import ipaddress
import re
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker, validators

from diaglab.exceptions import ArtifactIntegrityError
from diaglab.serialization import parse_json, require_json

FORMATS = FormatChecker()
PRIVATE_NETWORKS = tuple(
    ipaddress.IPv4Network(network) for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)


@FORMATS.checks("rfc1918-ipv4")
def private_ipv4(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        return False
    return any(address in network for network in PRIVATE_NETWORKS)


@FORMATS.checks("utc-rfc3339")
def utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", value
    ):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


# JSON Schema normally treats 1.0 as an integer. The lab forbids such coercion.
TYPES = Draft202012Validator.TYPE_CHECKER.redefine(
    "integer", lambda checker, value: type(value) is int
).redefine("number", lambda checker, value: type(value) in (int, float))
StrictValidator = validators.extend(Draft202012Validator, type_checker=TYPES)


@lru_cache(maxsize=8)
def validator(name: str) -> Draft202012Validator:
    if name not in {"experiment", "metric", "manifest", "summary"}:
        raise ArtifactIntegrityError(f"unknown schema: {name}")
    schema = parse_json(files("diaglab").joinpath("schemas", f"{name}.schema.json").read_text())
    StrictValidator.check_schema(schema)
    return StrictValidator(schema, format_checker=FORMATS)


def validate_record(name: str, record: Any) -> None:
    require_json(record)
    errors = []
    for error in validator(name).iter_errors(record):
        errors.extend(_actionable_errors(error))
    errors.sort(key=lambda error: tuple(str(part) for part in error.absolute_path))
    if errors:
        descriptions = []
        for error in errors[:8]:
            path = ".".join(str(part) for part in error.absolute_path) or "$"
            descriptions.append(f"{path}: {error.message}")
        raise ArtifactIntegrityError("; ".join(descriptions))


def _actionable_errors(error: Any) -> list[Any]:
    """Expand union errors only when exactly one tagged branch matches."""
    if error.validator in {"oneOf", "anyOf"} and isinstance(error.instance, dict):
        matches = []
        for index, branch in enumerate(error.validator_value):
            properties = branch.get("properties", {})
            discriminators = {
                key: rule for key, rule in properties.items() if "const" in rule or "enum" in rule
            }
            if discriminators and all(
                key in error.instance
                and (
                    error.instance[key] == rule["const"]
                    if "const" in rule
                    else error.instance[key] in rule["enum"]
                )
                for key, rule in discriminators.items()
            ):
                matches.append(index)
        if len(matches) == 1:
            children = [
                child
                for child in error.context
                if child.schema_path and child.schema_path[0] == matches[0]
            ]
            if children:
                return [detail for child in children for detail in _actionable_errors(child)]
    return [error]
