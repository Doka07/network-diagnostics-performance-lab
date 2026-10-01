"""Stable failures shared by the CLI and later lifecycle components."""


class DiaglabError(Exception):
    code = "DIAGLAB_ERROR"
    exit_code = 3


class ConfigValidationError(DiaglabError):
    code = "CONFIG_INVALID"
    exit_code = 1


class SafetyPreflightError(DiaglabError):
    code = "PREFLIGHT_REFUSED"
    exit_code = 1


class MissingInputError(DiaglabError):
    code = "INPUT_MISSING"
    exit_code = 2


class FaultInjectionError(DiaglabError):
    code = "FAULT_APPLY_FAILED"


class FaultCleanupError(DiaglabError):
    code = "FAULT_CLEANUP_FAILED"
    exit_code = 4


class TrafficExecutionError(DiaglabError):
    code = "TRAFFIC_FAILED"

    def __init__(self, message: str, *, reason_code: str = "TRAFFIC_FAILED") -> None:
        self.reason_code = reason_code
        super().__init__(message)


class TelemetryCollectionError(DiaglabError):
    code = "COLLECTION_FAILED"


class ArtifactIntegrityError(DiaglabError):
    code = "ARTIFACT_INVALID"


class NonfiniteValueError(ArtifactIntegrityError):
    """A numeric JSON value cannot be represented as a finite number."""
