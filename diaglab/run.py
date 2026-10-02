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
    TrafficExecutionError,
)
from diaglab.models import RunContext, VerificationResult
from diaglab.serialization import canonical_json, parse_json
from diaglab.traffic.parser import MAX_DOCUMENT_BYTES, parse_iperf3
from diaglab.traffic.runner import Iperf3TrafficAdapter
from diaglab.validation import validate_record
from diaglab.verification_support import _phase_scope, _report_valid, _traffic_identity

BASE_PAYLOADS = {"config.json", "command.json", "events.jsonl"}
RAW_PAYLOADS = {"client.json", "client.stderr"}


class RunInterrupted(DiaglabError):
    code = "INTERRUPTED"

    def __init__(self, signum: int) -> None:
        self.exit_code = 128 + signum
        super().__init__(f"run interrupted by signal {signum}")


@contextmanager
def _signals():
    previous = {}
    interrupted = False
    deferred = False
    pending = None

    def handler(signum, frame):
        nonlocal interrupted, pending
        if deferred:
            pending = pending or signum
            return
        if not interrupted:
            interrupted = True
            raise RunInterrupted(signum)

    @contextmanager
    def defer():
        nonlocal deferred, pending
        deferred = True
        try:
            yield
        finally:
            deferred = False
            if pending is not None:
                signum, pending = pending, None
                handler(signum, None)

    if threading.current_thread() is threading.main_thread():
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, handler)
    try:
        yield defer
    finally:
        for signum, old in previous.items():
            signal.signal(signum, old)


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
    with ArtifactStore(output, create=True) as store, _signals() as defer_signals:
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
                # Record interruptions until ownership is assigned; do not mask the child.
                with defer_signals():
                    handle = adapter.start(context)
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
                command["result_verified"] = _report_valid(report)
                summary = {"schema_version": "1.0", "report": report.to_dict()}
                validate_record("traffic_summary", summary)
                summary_bytes = canonical_json(summary) + b"\n"
                if len(summary_bytes) > MAX_DOCUMENT_BYTES:
                    command["result_verified"] = False
                    raise TrafficExecutionError(
                        "derived summary exceeds 16 MiB",
                        reason_code="SUMMARY_OUTPUT_LIMIT_EXCEEDED",
                    )
                store.write("traffic_summary.json", summary_bytes)
                command["transfer_completed"] = True
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
            command["result_verified"] = False
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
                    command["result_verified"] = False
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
                # Preserve honest terminal state even when payload finalization cannot finish.
                if manifest["state"] != "interrupted":
                    manifest["state"] = "failed"
                reasons = list(manifest["eligibility"]["reasons"])
                if "FINALIZATION_FAILED" not in reasons:
                    reasons.append("FINALIZATION_FAILED")
                manifest["eligibility"] = {"status": "rejected", "reasons": reasons}
                _event(events, "RUN_FAILED", "FINALIZATION_FAILED")
                manifest["events"] = events
                try:
                    store.replace_json("manifest.json", manifest)
                except Exception as emergency_error:
                    finalize_error.add_note(
                        f"Emergency manifest failed: {type(emergency_error).__name__}"
                    )
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
    from diaglab.inspection import load_run

    inspection = load_run(path, include_evidence=False)
    if inspection.verification is not None:
        return inspection.verification
    issue = inspection.issues[0]
    error = MissingInputError if issue.code == "INPUT_MISSING" else ArtifactIntegrityError
    raise error(f"{issue.code}: {issue.message}")
