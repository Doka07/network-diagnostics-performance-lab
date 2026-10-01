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


class TelemetryCollectionError(DiaglabError):
    code = "COLLECTION_FAILED"


class ArtifactIntegrityError(DiaglabError):
    code = "ARTIFACT_INVALID"
