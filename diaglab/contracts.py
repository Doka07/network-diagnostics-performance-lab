"""Lifecycle protocols for future components; Phase 1 executes none of them."""

from typing import Protocol

from diaglab.models import (
    AnalysisResult,
    CollectorCapabilities,
    MetricBatch,
    PreflightResult,
    RunArtifacts,
    RunContext,
    TrafficHandle,
    TrafficResult,
    VerificationResult,
)


class Collector(Protocol):
    capabilities: CollectorCapabilities
    cadence_hz: float
    timeout_s: float

    def prepare(self, context: RunContext) -> None: ...
    def collect(self, timestamp_ns: int) -> MetricBatch: ...
    def close(self) -> None: ...


class FaultInjector(Protocol):
    name: str

    def preflight(self, context: RunContext) -> PreflightResult: ...
    def apply(self, context: RunContext) -> None: ...
    def verify(self, context: RunContext) -> VerificationResult: ...
    def restore(self, context: RunContext) -> None: ...


class TrafficAdapter(Protocol):
    name: str

    def prepare(self, context: RunContext) -> None: ...
    def start(self, context: RunContext) -> TrafficHandle: ...
    def wait(self, handle: TrafficHandle) -> TrafficResult: ...
    def stop(self, handle: TrafficHandle) -> None: ...


class Analyzer(Protocol):
    name: str

    def analyze(self, run: RunArtifacts) -> AnalysisResult: ...


class PrivilegeHelper(Protocol):
    """Typed client boundary; installation/implementation requires Phase 4 review."""

    def preflight(self, context: RunContext) -> PreflightResult: ...
    def apply(self, context: RunContext, profile_id: str) -> None: ...
    def restore(self, lease_id: str) -> VerificationResult: ...
