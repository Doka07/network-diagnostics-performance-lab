"""Pure outcome and traffic identity rules shared by execution and inspection."""

from diaglab.config import ExperimentConfig
from diaglab.exceptions import ArtifactIntegrityError, SafetyPreflightError
from diaglab.serialization import parse_json

UNVERIFIED_FLAGS = {
    "RECEIVER_SOURCE_MISMATCH",
    "SERVER_OUTPUT_UNAVAILABLE",
    "REPORTED_RATE_MISMATCH",
    "INTERVAL_GAP",
    "OMIT_METADATA_MISMATCH",
}


def _phase_scope(config: ExperimentConfig, run_role: str, execute: bool) -> None:
    data = config.data
    if run_role not in {"warmup", "pilot"}:
        raise SafetyPreflightError("Phase 2 only supports warmup and pilot roles")
    if data["scenario"]["kind"] != "baseline" or data["traffic"]["streams"] not in (1, 4):
        raise SafetyPreflightError("Phase 2 requires baseline and one or four streams")
    if execute and (
        data["evidence_kind"] != "pilot"
        or data["safety"]["dry_run"]
        or not data["safety"]["approved_profile_id"]
    ):
        raise SafetyPreflightError(
            "--execute requires pilot evidence, dry_run false and profile ID"
        )


def _report_valid(report) -> bool:
    return not UNVERIFIED_FLAGS.intersection(report.quality_flags)


def _traffic_identity(config: ExperimentConfig, source: str, raw: str, report) -> None:
    record = parse_json(raw)
    duration = record.get("start", {}).get("test_start", {}).get("duration")
    if type(duration) not in (int, float) or duration != config.data["traffic"]["duration_s"]:
        raise ArtifactIntegrityError("iperf3 duration setting differs from approved configuration")
    for flow in report.flows:
        if (
            flow.local_host != source
            or flow.remote_host != config.data["target"]["host"]
            or flow.remote_port != config.data["target"]["port"]
        ):
            raise ArtifactIntegrityError("iperf3 socket identities differ from approved target")
