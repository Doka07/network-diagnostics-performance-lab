"""Offline experiment configuration. Loading never executes a host command."""

import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken, TagToken

from diaglab.exceptions import ArtifactIntegrityError, ConfigValidationError, MissingInputError
from diaglab.serialization import content_hash, plain_json
from diaglab.validation import validate_record

MAX_CONFIG_BYTES = 1_048_576
# Initial capabilities are conservative contracts; Phase 3 must measure actual cost.
COLLECTOR_LIMITS = MappingProxyType(
    {
        "proc_net_dev": 50.0,
        "proc_net_snmp": 50.0,
        "proc_stat": 50.0,
        "process_stats": 50.0,
        "scheduler": 50.0,
        "tc_qdisc": 1.0,
        "ethtool": 1.0,
        "socket_stats": 1.0,
    }
)


class StrictLoader(yaml.SafeLoader):
    """JSON-compatible YAML without YAML 1.1 boolean coercion or merge keys."""


StrictLoader.yaml_implicit_resolvers = {
    key: [
        entry
        for entry in values
        if entry[0]
        not in {
            "tag:yaml.org,2002:bool",
            "tag:yaml.org,2002:timestamp",
            "tag:yaml.org,2002:int",
            "tag:yaml.org,2002:float",
        }
    ]
    for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf")
)
StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int", re.compile(r"^-?(?:0|[1-9][0-9]*)$"), list("-0123456789")
)
StrictLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+(?:[eE][+-]?[0-9]+)?|[eE][+-]?[0-9]+)$"),
    list("-0123456789"),
)


def _mapping(loader: StrictLoader, node: MappingNode) -> dict[str, Any]:
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if type(key) is not str:
            raise ConfigValidationError("configuration mapping keys must be strings")
        if key in result:
            raise ConfigValidationError(f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=True)
    return result


StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class ExperimentConfig:
    data: Any

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExperimentConfig":
        try:
            normalized = plain_json(data)
        except ArtifactIntegrityError as exc:
            raise ConfigValidationError(str(exc)) from exc
        if type(normalized) is not dict:
            raise ConfigValidationError("configuration root must be an object")
        if isinstance(normalized.get("safety"), dict):
            normalized["safety"].setdefault("allow_default_route", False)
            normalized["safety"].setdefault("dry_run", True)
            normalized["safety"].setdefault("approved_profile_id", None)
        if isinstance(normalized.get("traffic"), dict):
            normalized["traffic"].setdefault("omit_s", 0)
        try:
            validate_record("experiment", normalized)
        except ArtifactIntegrityError as exc:
            raise ConfigValidationError(f"invalid configuration: {exc}") from exc
        target = normalized["target"]
        if target["interface"] not in normalized["safety"]["allowlist_interfaces"]:
            raise ConfigValidationError("target.interface is not in safety.allowlist_interfaces")
        if (
            not normalized["safety"]["dry_run"]
            and normalized["safety"]["approved_profile_id"] is None
        ):
            raise ConfigValidationError(
                "safety.approved_profile_id is required when dry_run is false"
            )
        if normalized["traffic"]["omit_s"] >= normalized["traffic"]["duration_s"]:
            raise ConfigValidationError("traffic.omit_s must be less than duration_s")
        seen = set()
        for collector in normalized["telemetry"]["collectors"]:
            name = collector["name"]
            if name in seen:
                raise ConfigValidationError(f"duplicate collector: {name}")
            seen.add(name)
            if name not in COLLECTOR_LIMITS:
                raise ConfigValidationError(f"unknown collector: {name}")
            if collector["cadence_hz"] > COLLECTOR_LIMITS[name]:
                raise ConfigValidationError(f"collector {name} exceeds maximum safe cadence")
        return cls(freeze(normalized))

    def to_dict(self) -> dict[str, Any]:
        return plain_json(self.data)

    @property
    def sha256(self) -> str:
        return content_hash(self.data)


def load_config(path: str | Path) -> ExperimentConfig:
    path = Path(path)
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_CONFIG_BYTES + 1)
    except FileNotFoundError as exc:
        raise MissingInputError(f"configuration file not found: {path}") from exc
    except OSError as exc:
        raise ConfigValidationError(f"cannot read configuration: {exc}") from exc
    if len(raw) > MAX_CONFIG_BYTES:
        raise ConfigValidationError("configuration exceeds 1 MiB")
    try:
        text = raw.decode("utf-8")
        if any(isinstance(token, (AliasToken, AnchorToken, TagToken)) for token in yaml.scan(text)):
            raise ConfigValidationError("YAML aliases, anchors, and explicit tags are unsupported")
        data = yaml.load(text, Loader=StrictLoader)
        if type(data) is not dict:
            raise ConfigValidationError("configuration root must be an object")
        return ExperimentConfig.from_dict(data)
    except (yaml.YAMLError, UnicodeError, RecursionError) as exc:
        raise ConfigValidationError(f"invalid YAML: {exc}") from exc
    except ArtifactIntegrityError as exc:
        raise ConfigValidationError(str(exc)) from exc
