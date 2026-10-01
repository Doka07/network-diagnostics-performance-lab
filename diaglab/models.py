"""Immutable data boundaries; lifecycle records have no active implementations."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from diaglab.config import ExperimentConfig, freeze
from diaglab.exceptions import ArtifactIntegrityError
from diaglab.serialization import canonical_json, parse_json, plain_json
from diaglab.validation import validate_record


class EvidenceKind(StrEnum):
    PILOT = "pilot"
    MEASURED = "measured"
    SYNTHETIC = "synthetic"


class DiagnosticStatus(StrEnum):
    NO_DEGRADATION = "NO_DEGRADATION"
    SINGLE_HINT = "SINGLE_HINT"
    MULTIPLE_CONTRIBUTORS = "MULTIPLE_CONTRIBUTORS"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True)
class MetricBatch:
    """One collection epoch; validation applies even to direct construction."""

    data: Mapping[str, Any]

    def __post_init__(self) -> None:
        record = plain_json(self.data)
        validate_record("metric", record)
        start = record["collection_start_monotonic_ns"]
        end = record["collection_end_monotonic_ns"]
        if end < start or record["monotonic_ns"] < start or record["monotonic_ns"] > end:
            raise ArtifactIntegrityError("collection timestamps are not ordered")
        keys = set()
        for metric in record["metrics"]:
            key = (metric["name"], metric["scope"], canonical_json(metric["tags"]))
            if key in keys:
                raise ArtifactIntegrityError("duplicate metric series within a collection batch")
            keys.add(key)
        object.__setattr__(self, "data", freeze(record))

    @classmethod
    def from_dict(cls, record: Mapping[str, Any]) -> "MetricBatch":
        return cls(record)

    @classmethod
    def from_json_line(cls, line: str) -> "MetricBatch":
        return cls(parse_json(line))

    def to_dict(self) -> dict[str, Any]:
        return plain_json(self.data)

    def to_json_line(self) -> str:
        return canonical_json(self.data).decode("utf-8") + "\n"

    def flatten(self) -> tuple[dict[str, Any], ...]:
        header = {key: value for key, value in self.to_dict().items() if key != "metrics"}
        return tuple({**header, "metric": plain_json(metric)} for metric in self.data["metrics"])

    @classmethod
    def from_flat_records(cls, records: Sequence[Mapping[str, Any]]) -> "MetricBatch":
        if not records:
            raise ArtifactIntegrityError("flat records must contain at least one metric")
        items = [plain_json(record) for record in records]
        if any("metric" not in record for record in items):
            raise ArtifactIntegrityError("flat record has no metric")
        header = {key: value for key, value in items[0].items() if key != "metric"}
        if any(
            {key: value for key, value in item.items() if key != "metric"} != header
            for item in items
        ):
            raise ArtifactIntegrityError("flat records belong to different collection epochs")
        return cls({**header, "metrics": [item["metric"] for item in items]})


@dataclass(frozen=True)
class CollectorCapabilities:
    name: str
    cost_class: str
    max_safe_cadence_hz: float


@dataclass(frozen=True)
class RunContext:
    run_id: str
    config: ExperimentConfig
    artifact_root: Path


@dataclass(frozen=True)
class PreflightResult:
    allowed: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class TrafficHandle:
    pid: int
    process_group_id: int
    started_monotonic_ns: int


@dataclass(frozen=True)
class TrafficResult:
    returncode: int
    stdout_artifact: str
    stderr_artifact: str
    timed_out: bool = False


@dataclass(frozen=True)
class ClockEstimate:
    method: str
    offset_ns: int | None = None
    uncertainty_ns: int | None = None
    measured_at_utc: str | None = None
    drift_ns_per_s: float | None = None
    valid: bool = False


@dataclass(frozen=True)
class AgentSession:
    campaign_id: str
    session_id: str
    host_id: str
    version: str
    clock: ClockEstimate


@dataclass(frozen=True)
class FaultLease:
    lease_id: str
    run_id: str
    interface: str
    profile_id: str
    initial_structure_sha256: str
    expires_at_utc: str


@dataclass(frozen=True)
class AnalysisSample:
    """Measured features only: no file paths, scenario identities, or commands."""

    collector: str
    host_id: str
    timestamp_utc: str
    monotonic_ns: int
    name: str
    value: int | float | None
    unit: str
    scope: str
    tags: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    data_quality_flags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        allowed = {"interface", "direction", "flow_id", "core_id", "queue_id", "qdisc_kind"}
        if set(self.tags) - allowed:
            raise ArtifactIntegrityError(
                "analysis tags contain fields outside measured feature scope"
            )
        object.__setattr__(self, "tags", freeze(plain_json(self.tags)))


@dataclass(frozen=True)
class RunArtifacts:
    """Blinded analysis boundary. It cannot carry controller configuration."""

    samples: tuple[AnalysisSample, ...]

    def __post_init__(self) -> None:
        if any(not isinstance(sample, AnalysisSample) for sample in self.samples):
            raise ArtifactIntegrityError("RunArtifacts accepts AnalysisSample objects only")
        object.__setattr__(self, "samples", tuple(self.samples))


@dataclass(frozen=True)
class AnalysisResult:
    status: DiagnosticStatus
    contributors: tuple[str, ...]
    supporting_evidence: tuple[str, ...]
    contradicting_evidence: tuple[str, ...]
    alternatives: tuple[str, ...]
    limitations: tuple[str, ...]
    confidence_rationale: str
    data_quality_flags: tuple[str, ...] = ()
