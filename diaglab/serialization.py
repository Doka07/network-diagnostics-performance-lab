"""JSON primitives: finite values, canonical hashes, and strict decoding."""

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from diaglab.exceptions import ArtifactIntegrityError


def require_json(value: Any, path: str = "$", seen: set[int] | None = None) -> None:
    """Reject coercion, NaN, non-string keys, cycles, and non-JSON Python values."""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise ArtifactIntegrityError(f"{path}: nonfinite number")
        return
    if isinstance(value, Mapping) or isinstance(value, (list, tuple)):
        seen = set() if seen is None else seen
        identity = id(value)
        if identity in seen:
            raise ArtifactIntegrityError(f"{path}: cyclic structure")
        seen.add(identity)
        try:
            if isinstance(value, Mapping):
                for key, item in value.items():
                    if type(key) is not str:
                        raise ArtifactIntegrityError(f"{path}: mapping keys must be strings")
                    require_json(item, f"{path}.{key}", seen)
            else:
                for index, item in enumerate(value):
                    require_json(item, f"{path}[{index}]", seen)
        finally:
            seen.remove(identity)
        return
    raise ArtifactIntegrityError(f"{path}: unsupported value type {type(value).__name__}")


def plain_json(value: Any) -> Any:
    """Make mappings and immutable sequences serializable without type coercion."""
    require_json(value)
    if isinstance(value, Mapping):
        return {key: plain_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain_json(item) for item in value]
    return value


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        plain_json(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArtifactIntegrityError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ArtifactIntegrityError(f"nonfinite JSON value: {value}")


def parse_json(text: str) -> Any:
    try:
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, RecursionError) as exc:
        raise ArtifactIntegrityError(f"invalid JSON: {exc}") from exc
    require_json(value)
    return value
