"""Phase 2 run orchestration and offline artifact verification; no remote mutation."""

import math
import signal
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from diaglab.artifacts.manifest import planned_manifest
from diaglab.artifacts.store import ArtifactStore
from diaglab.config import ExperimentConfig
from diaglab.exceptions import (
    ArtifactIntegrityError,
    DiaglabError,
    FaultCleanupError,
    MissingInputError,
    SafetyPreflightError,
    TrafficExecutionError,
)
from diaglab.models import RunContext, VerificationResult
from diaglab.serialization import canonical_json, parse_json
from diaglab.traffic.parser import MAX_DOCUMENT_BYTES, parse_iperf3
from diaglab.traffic.runner import Iperf3TrafficAdapter
from diaglab.validation import validate_record

BASE_PAYLOADS = {"config.json", "command.json", "events.jsonl"}
RAW_PAYLOADS = {"client.json", "client.stderr"}
UNVERIFIED_FLAGS = {
    "RECEIVER_SOURCE_MISMATCH",
    "SERVER_OUTPUT_UNAVAILABLE",
    "REPORTED_RATE_MISMATCH",
    "INTERVAL_GAP",
    "OMIT_METADATA_MISMATCH",
}


class RunInterrupted(DiaglabError):
    code = "INTERRUPTED"

    def __init__(self, signum: int) -> None:
        self.exit_code = 128 + signum
        super().__init__(f"run interrupted by signal {signum}")


@contextmanager
def _signals():
    previous = {}
    interrupted = False

    def handler(signum, frame):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise RunInterrupted(signum)

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, handler)
    try:
        yield
    finally:
        for signum, old in previous.items():
            signal.signal(signum, old)


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


def _decode(store: ArtifactStore, name: str, *, limit: int = MAX_DOCUMENT_BYTES):
    try:
        return parse_json(store.read(name, limit=limit).decode("utf-8"))
    except (UnicodeError, RecursionError) as exc:
        raise ArtifactIntegrityError(f"invalid artifact encoding: {name}") from exc


def _event(events: list[dict], name: str, message: str | None = None) -> None:
    record = {
        "name": name,
        "timestamp_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "monotonic_ns": time.monotonic_ns(),
    }
    if message:
        record["message"] = message[:256]
    events.append(record)


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


def run_experiment(
    config: ExperimentConfig,
    output: Path,
    *,
    execute: bool = False,
    run_role: str = "pilot",
    executable: str = "iperf3",
) -> Path:
    _phase_scope(config, run_role, execute)
    output = Path(output)
    manifest = planned_manifest(config, run_role=run_role)
    context = RunContext(manifest["run_id"], config, output)
    events = []
    failure = None
    handle = None
    adapter = Iperf3TrafficAdapter(executable=executable)
    command = {
        "schema_version": "1.0",
        "execute": execute,
        "argv": [],
        "source_ip": None,
        "result_verified": False,
        "transfer_completed": False,
        "returncode": None,
        "timeout_stage": None,
        "failure_reason": None,
    }
    with ArtifactStore(output, create=True) as store, _signals():
        store.write_json("manifest.json", manifest)
        store.write_json("config.json", config.to_dict())
        _event(events, "RUN_PLANNED")
        try:
            if execute:
                _event(events, "LIVE_PREFLIGHT_STARTED")
                adapter.prepare(context)
                _event(events, "LIVE_PREFLIGHT_PASSED")
                command["argv"] = list(adapter.command)
                command["source_ip"] = adapter.source
                manifest["state"] = "running"
                manifest["cleanup"] = {"status": "pending", "reasons": []}
                manifest["events"] = events.copy()
                store.replace_json("manifest.json", manifest)
                # Defer signals until the owned handle is available to final cleanup.
                previous_mask = signal.pthread_sigmask(
                    signal.SIG_BLOCK, {signal.SIGINT, signal.SIGTERM}
                )
                try:
                    handle = adapter.start(context)
                finally:
                    signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
                _event(events, "TRAFFIC_STARTED")
                result = adapter.wait(handle)
                command["returncode"] = result.returncode
                command["timeout_stage"] = result.timeout_stage
                command["failure_reason"] = result.failure_reason
                if not result.cleanup_verified:
                    raise FaultCleanupError("traffic process cleanup not verified")
                if result.returncode or result.failure_reason:
                    raise TrafficExecutionError(
                        result.failure_reason or "iperf3 failed",
                        reason_code=result.failure_reason or "TRAFFIC_FAILED",
                    )
                _event(events, "TRAFFIC_EXITED")
                raw = store.read("client.json").decode("utf-8")
                report = parse_iperf3(
                    raw,
                    expected_streams=config.data["traffic"]["streams"],
                    omit_s=config.data["traffic"]["omit_s"],
                )
                _traffic_identity(config, adapter.source, raw, report)
                command["transfer_completed"] = True
                command["result_verified"] = _report_valid(report)
                summary = {"schema_version": "1.0", "report": report.to_dict()}
                validate_record("traffic_summary", summary)
                store.write_json("traffic_summary.json", summary)
                if not command["result_verified"]:
                    raise TrafficExecutionError(
                        "traffic output did not reconcile",
                        reason_code="TRAFFIC_OUTPUT_INCONSISTENT",
                    )
                manifest["state"] = "completed"
                _event(events, "TRAFFIC_VERIFIED")
            else:
                # Symbolic source: no ip query, binary discovery, socket, or subprocess.
                traffic, target = config.data["traffic"], config.data["target"]
                command["argv"] = [
                    "iperf3",
                    "-c",
                    target["host"],
                    "-B",
                    "<LIVE_SOURCE_IP>",
                    "-p",
                    str(target["port"]),
                    "-t",
                    str(traffic["duration_s"]),
                    "-P",
                    str(traffic["streams"]),
                    "-O",
                    str(traffic["omit_s"]),
                    "-J",
                    "--get-server-output",
                    "--connect-timeout",
                    str(math.ceil(traffic["connect_timeout_s"] * 1000)),
                ]
        except BaseException as exc:
            failure = exc
            manifest["state"] = (
                "interrupted" if isinstance(exc, (RunInterrupted, KeyboardInterrupt)) else "failed"
            )
            command["failure_reason"] = getattr(
                exc, "reason_code", getattr(exc, "code", "INTERNAL_ERROR")
            )
            _event(events, "RUN_FAILED", command["failure_reason"])
        finally:
            if handle is not None:
                try:
                    adapter.stop(handle)
                    # On interruption wait() may not yet have returned its final process record.
                    outcome = adapter.wait(handle)
                    command["returncode"] = outcome.returncode
                    command["timeout_stage"] = outcome.timeout_stage
                    manifest["cleanup"] = {"status": "verified", "reasons": []}
                    _event(events, "CLEANUP_VERIFIED")
                except BaseException as exc:
                    failure = (
                        exc if isinstance(exc, FaultCleanupError) else FaultCleanupError(str(exc))
                    )
                    command["failure_reason"] = failure.code
                    manifest["state"] = "failed"
                    manifest["cleanup"] = {
                        "status": "unverifiable",
                        "reasons": [str(failure)[:256]],
                    }
                    _event(events, "CLEANUP_FAILED")
            if manifest["state"] in {"failed", "interrupted"}:
                manifest["eligibility"] = {
                    "status": "rejected",
                    "reasons": [command["failure_reason"]],
                }
            elif execute:
                manifest["eligibility"]["reasons"] = ["PILOT_ONLY", "NOT_IMPLEMENTED_PHASE2"]
            for collector in config.data["telemetry"]["collectors"]:
                expected = (
                    math.ceil(config.data["traffic"]["duration_s"] * collector["cadence_hz"])
                    if execute
                    else 0
                )
                manifest["collector_coverage"].append(
                    {
                        "collector": collector["name"],
                        "expected_samples": expected,
                        "actual_samples": 0,
                        "missed_samples": expected,
                        "required": collector["required"],
                        "unavailability_reason": "NOT_IMPLEMENTED_PHASE2",
                    }
                )
            manifest["events"] = events
            try:
                validate_record("run_command", command)
                store.write_json("command.json", command)
                store.write(
                    "events.jsonl", b"".join(canonical_json(item) + b"\n" for item in events)
                )
                names = store.names() - {"manifest.json", ".run.lock"}
                payloads = [store.digest(name) for name in sorted(names)]
                checksums = {"schema_version": "1.0", "files": payloads}
                validate_record("checksums", checksums)
                store.write_json("checksums.json", checksums)
                manifest["artifacts"] = payloads + [store.digest("checksums.json")]
                validate_record("manifest", manifest)
                store.replace_json("manifest.json", manifest)
            except BaseException as finalize_error:
                if failure is not None:
                    if isinstance(failure, FaultCleanupError):
                        failure.add_note(f"Artifact finalization also failed: {finalize_error}")
                        raise failure from finalize_error
                    raise finalize_error from failure
                raise
    if failure is not None:
        raise failure
    return output / "manifest.json"


def verify_run(path: Path) -> VerificationResult:
    with ArtifactStore(path) as store:
        manifest = _decode(store, "manifest.json", limit=1024 * 1024)
        validate_record("manifest", manifest)
        # A Phase 1 planned manifest has no Phase 2 evidence to verify.
        if manifest["state"] == "planned" and not manifest["artifacts"]:
            if store.names() != {"manifest.json"}:
                raise ArtifactIntegrityError("unexpected files in planned run")
            return VerificationResult(True, ("PLANNED_ONLY",), "planned")
        if manifest["state"] == "running" or ".run.lock" in store.names():
            raise ArtifactIntegrityError("run has not been finalized")
        checksums = _decode(store, "checksums.json", limit=1024 * 1024)
        validate_record("checksums", checksums)
        entries = checksums["files"]
        paths = [entry["path"] for entry in entries]
        manifest_entries = {entry["path"]: entry for entry in manifest["artifacts"]}
        if len(paths) != len(set(paths)) or len(manifest_entries) != len(manifest["artifacts"]):
            raise ArtifactIntegrityError("duplicate artifact digest entries")
        if set(manifest_entries) != set(paths) | {"checksums.json"}:
            raise ArtifactIntegrityError("manifest/checksum path coverage differs")
        for entry in entries:
            if store.digest(entry["path"]) != entry or manifest_entries[entry["path"]] != entry:
                raise ArtifactIntegrityError(f"artifact digest mismatch: {entry['path']}")
        if store.digest("checksums.json") != manifest_entries["checksums.json"]:
            raise ArtifactIntegrityError("checksums file digest mismatch")
        if store.names() != set(manifest_entries) | {"manifest.json"}:
            raise ArtifactIntegrityError("unexpected or unlisted files in run")
        config = ExperimentConfig.from_dict(_decode(store, "config.json", limit=1024 * 1024))
        if (
            config.sha256 != manifest["config_sha256"]
            or config.data["campaign_id"] != manifest["campaign_id"]
        ):
            raise ArtifactIntegrityError("config identity mismatch")
        command = _decode(store, "command.json", limit=1024 * 1024)
        validate_record("run_command", command)
        try:
            _phase_scope(config, manifest["run_role"], command["execute"])
        except SafetyPreflightError as exc:
            raise ArtifactIntegrityError(f"invalid recorded phase scope: {exc}") from exc
        if config.data["evidence_kind"] != manifest["evidence_kind"]:
            raise ArtifactIntegrityError("config evidence kind differs from manifest")
        expected = BASE_PAYLOADS.copy()
        if RAW_PAYLOADS.intersection(paths):
            expected |= RAW_PAYLOADS
        if "traffic_summary.json" in paths:
            expected.add("traffic_summary.json")
        if set(paths) != expected:
            raise ArtifactIntegrityError("missing required or unexpected payload coverage")
        if command["execute"] is False and (
            manifest["state"] != "planned" or expected != BASE_PAYLOADS
        ):
            raise ArtifactIntegrityError("offline plan is inconsistent with execution artifacts")
        events = [
            _decode_event(line)
            for line in store.read("events.jsonl", limit=1024 * 1024).splitlines()
        ]
        if events != manifest["events"]:
            raise ArtifactIntegrityError("manifest event history differs from event artifact")
        if any(
            event["name"] == "TRAFFIC_STARTED" for event in events
        ) and not RAW_PAYLOADS.issubset(paths):
            raise ArtifactIntegrityError("started process is missing raw output artifacts")
        if command["returncode"] is not None and not RAW_PAYLOADS.issubset(paths):
            raise ArtifactIntegrityError("process exit is missing raw output artifacts")
        completed = command["transfer_completed"]
        verified = False
        if manifest["state"] == "completed" and (
            not command["execute"]
            or not RAW_PAYLOADS.issubset(paths)
            or "traffic_summary.json" not in paths
            or command.get("returncode") != 0
            or manifest["cleanup"]["status"] != "verified"
            or not completed
        ):
            raise ArtifactIntegrityError("completed run lacks required transfer evidence")
        if "traffic_summary.json" in paths:
            summary = _decode(store, "traffic_summary.json")
            validate_record("traffic_summary", summary)
            raw = store.read("client.json").decode("utf-8")
            report = parse_iperf3(
                raw,
                expected_streams=config.data["traffic"]["streams"],
                omit_s=config.data["traffic"]["omit_s"],
            )
            if report.to_dict() != summary["report"]:
                raise ArtifactIntegrityError("traffic summary differs from reconstructed report")
            if not command["execute"] or command["returncode"] != 0 or not completed:
                raise ArtifactIntegrityError("summary is inconsistent with process outcome")
            _traffic_identity(config, command["source_ip"], raw, report)
            verified = _report_valid(report)
            if manifest["state"] == "completed" and not verified:
                raise ArtifactIntegrityError("completed run has unreconciled traffic result")
        elif manifest["state"] == "completed":
            raise MissingInputError("completed run lacks traffic summary")
        if (
            type(command.get("result_verified")) is not bool
            or command["result_verified"] != verified
        ):
            raise ArtifactIntegrityError("recorded verification outcome differs from evidence")
        return VerificationResult(True, (), manifest["state"], completed, verified)


def _decode_event(line: bytes) -> dict:
    try:
        return parse_json(line.decode())
    except UnicodeError as exc:
        raise ArtifactIntegrityError("invalid event encoding") from exc
