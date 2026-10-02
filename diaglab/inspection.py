"""Read-only, bounded artifact snapshots and shared verification for CLI and desktop."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from threading import Event
from types import MappingProxyType

from diaglab.artifacts.checksums import open_directory
from diaglab.config import ExperimentConfig
from diaglab.exceptions import (
    ArtifactIntegrityError,
    ConfigValidationError,
    NonfiniteValueError,
    SafetyPreflightError,
    TrafficExecutionError,
)
from diaglab.models import VerificationResult
from diaglab.serialization import parse_json
from diaglab.traffic.parser import Iperf3Report, parse_iperf3
from diaglab.validation import validate_record
from diaglab.verification_support import _phase_scope, _report_valid, _traffic_identity

MIB = 1024 * 1024
LIMITS = {
    name: MIB
    for name in (
        "manifest.json",
        "config.json",
        "command.json",
        "events.jsonl",
        "checksums.json",
        "client.stderr",
    )
}
LIMITS.update({"client.json": 16 * MIB, "traffic_summary.json": 16 * MIB})
LOCKS = {".run.lock", ".creation.lock"}
BASE_PAYLOADS = {"config.json", "command.json", "events.jsonl"}
RAW_PAYLOADS = {"client.json", "client.stderr"}


class IntegrityStatus(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    UNFINALIZED = "unfinalized"
    CANCELLED = "cancelled"


class InspectionCode(StrEnum):
    INPUT_MISSING = "INPUT_MISSING"
    PLATFORM_UNSUPPORTED = "PLATFORM_UNSUPPORTED"
    PATH_UNSAFE = "PATH_UNSAFE"
    NONREGULAR_FILE = "NONREGULAR_FILE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    RUN_TOO_LARGE = "RUN_TOO_LARGE"
    ENTRY_LIMIT_EXCEEDED = "ENTRY_LIMIT_EXCEEDED"
    READ_FAILED = "READ_FAILED"
    SNAPSHOT_CHANGED = "SNAPSHOT_CHANGED"
    INVALID_UTF8 = "INVALID_UTF8"
    INVALID_JSON = "INVALID_JSON"
    NONFINITE_VALUE = "NONFINITE_VALUE"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    CHECKSUM_MISMATCH = "CHECKSUM_MISMATCH"
    ARTIFACT_COVERAGE_MISMATCH = "ARTIFACT_COVERAGE_MISMATCH"
    CONFIG_IDENTITY_MISMATCH = "CONFIG_IDENTITY_MISMATCH"
    EVENT_HISTORY_MISMATCH = "EVENT_HISTORY_MISMATCH"
    RESULT_MISMATCH = "RESULT_MISMATCH"
    RUN_UNFINALIZED = "RUN_UNFINALIZED"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True)
class InspectionIssue:
    code: InspectionCode
    path: str | None
    message: str


@dataclass(frozen=True)
class ArtifactSnapshot:
    name: str
    data: bytes | None
    sha256: str | None
    size_bytes: int | None
    issue: InspectionIssue | None = None
    expected_sha256: str | None = None
    digest_status: str = "unlisted"


@dataclass(frozen=True)
class RunSnapshot:
    root: Path
    artifacts: tuple[ArtifactSnapshot, ...]
    entry_names: tuple[str, ...]
    issues: tuple[InspectionIssue, ...]
    finalized: bool


@dataclass(frozen=True)
class EvidenceReference:
    artifact: str
    json_pointer: str
    sha256: str
    source: str
    derivation: str | None = None
    inputs: tuple[str, ...] = ()


@dataclass(frozen=True)
class RunInspection:
    snapshot: RunSnapshot
    integrity: IntegrityStatus
    issues: tuple[InspectionIssue, ...]
    verification: VerificationResult | None = None
    state: str | None = None
    eligibility: str | None = None
    report: Iperf3Report | None = None
    manifest: Mapping | None = None
    evidence: tuple[EvidenceReference, ...] = ()
    # Stable semantic keys map report fields to raw provenance, resolved here, never in Qt.
    evidence_map: Mapping = field(default_factory=lambda: MappingProxyType({}))
    failure_reason: str | None = None


class _InspectionFailure(Exception):
    def __init__(self, code, message, path=None):
        self.issue = InspectionIssue(InspectionCode(code), path, message[:512])
        super().__init__(message)


def _reject(code, message, path=None):
    raise _InspectionFailure(code, message, path)


def _cancel(event):
    if event is not None and event.is_set():
        _reject("CANCELLED", "Loading cancelled")


def _meta(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    return value


def capture_run(
    path: Path, *, cancel: Event | None = None, progress: Callable[[int, int], None] | None = None
) -> RunSnapshot:
    root = Path(path).absolute()
    artifacts, issues, names = [], [], ()
    fd = -1
    try:
        _cancel(cancel)
        if sys.platform.startswith("win"):
            _reject("PLATFORM_UNSUPPORTED", "Offline viewer requires Linux/POSIX")
        try:
            fd = open_directory(root)
        except FileNotFoundError:
            _reject("INPUT_MISSING", "Run directory is missing")
        except (OSError, ArtifactIntegrityError, SafetyPreflightError):
            _reject("PATH_UNSAFE", "Run directory cannot be opened securely")
        root_before = _meta(os.fstat(fd))
        # scandir is bounded even when a directory contains arbitrarily many entries.
        with os.scandir(fd) as listing:
            entries = []
            for entry in listing:
                entries.append(entry.name)
                if len(entries) > 16:
                    _reject("ENTRY_LIMIT_EXCEEDED", "Run contains more than 16 entries")
        names = tuple(sorted(entries))
        before = {name: _meta(os.stat(name, dir_fd=fd, follow_symlinks=False)) for name in names}
        total_bytes = 0
        allowed = sorted(set(names) & LIMITS.keys())
        for index, name in enumerate(allowed):
            _cancel(cancel)
            handle = -1
            try:
                mode = before[name][2]
                if stat.S_ISLNK(mode):
                    _reject("PATH_UNSAFE", "Symlinked artifact refused", name)
                if not stat.S_ISREG(mode):
                    _reject("NONREGULAR_FILE", "Artifact must be a regular file", name)
                if before[name][3] > LIMITS[name]:
                    _reject("FILE_TOO_LARGE", "Artifact exceeds its byte limit", name)
                handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                if _meta(os.fstat(handle)) != before[name]:
                    _reject("SNAPSHOT_CHANGED", "Artifact changed before reading", name)
                chunks, size = [], 0
                while True:
                    _cancel(cancel)
                    chunk = os.read(handle, min(65536, LIMITS[name] + 1 - size))
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > LIMITS[name]:
                        _reject("FILE_TOO_LARGE", "Artifact exceeds its byte limit", name)
                    chunks.append(chunk)
                if _meta(os.fstat(handle)) != before[name]:
                    _reject("SNAPSHOT_CHANGED", "Artifact changed while reading", name)
                data = b"".join(chunks)
                total_bytes += len(data)
                if total_bytes > 48 * MIB:
                    _reject("RUN_TOO_LARGE", "Snapshot exceeds its byte limit")
                artifacts.append(
                    ArtifactSnapshot(name, data, hashlib.sha256(data).hexdigest(), size)
                )
            except _InspectionFailure as exc:
                if exc.issue.code == "CANCELLED":
                    raise
                artifacts.append(ArtifactSnapshot(name, None, None, None, exc.issue))
                issues.append(exc.issue)
            except OSError as exc:
                code = "PATH_UNSAFE" if exc.errno == errno.ELOOP else "READ_FAILED"
                issue = InspectionIssue(InspectionCode(code), name, "Cannot read artifact securely")
                artifacts.append(ArtifactSnapshot(name, None, None, None, issue))
                issues.append(issue)
            finally:
                if handle >= 0:
                    os.close(handle)
            if progress is not None:
                progress(index + 1, len(allowed))
            _cancel(cancel)
        check = open_directory(root)
        try:
            unchanged = _meta(os.fstat(check)) == root_before
        finally:
            os.close(check)
        with os.scandir(fd) as listing:
            after_names = sorted(entry.name for entry in listing)
        if (
            not unchanged
            or after_names != list(names)
            or any(
                _meta(os.stat(name, dir_fd=fd, follow_symlinks=False)) != before[name]
                for name in names
            )
        ):
            _reject("SNAPSHOT_CHANGED", "Run changed during capture")
    except _InspectionFailure as exc:
        issues.insert(0, exc.issue)
    except OSError:
        issues.insert(
            0,
            InspectionIssue(
                InspectionCode.SNAPSHOT_CHANGED, None, "Run became unavailable during capture"
            ),
        )
    finally:
        if fd >= 0:
            os.close(fd)
    return RunSnapshot(root, tuple(artifacts), names, tuple(issues), not bool(set(names) & LOCKS))


class _SnapshotStore:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.artifacts = {item.name: item for item in snapshot.artifacts}

    def read(self, name, **kwargs):
        if name not in self.artifacts:
            _reject("INPUT_MISSING", "Required artifact is missing", name)
        artifact = self.artifacts[name]
        if artifact.issue:
            raise _InspectionFailure(artifact.issue.code, artifact.issue.message, name)
        return artifact.data

    def digest(self, name):
        self.read(name)
        item = self.artifacts[name]
        return {"path": name, "size_bytes": item.size_bytes, "sha256": item.sha256}

    def names(self):
        return set(self.snapshot.entry_names)


def _json(data: bytes, name: str):
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        _reject("INVALID_UTF8", "Artifact is not UTF-8", name)
    # Check nesting without parsing or interpreting brackets inside quoted strings.
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 64:
                _reject("INVALID_JSON", "JSON nesting exceeds 64 levels", name)
        elif char in "]}":
            depth -= 1
    try:
        return parse_json(text)
    except NonfiniteValueError:
        _reject("NONFINITE_VALUE", "Nonfinite JSON number", name)
    except (ArtifactIntegrityError, RecursionError):
        _reject("INVALID_JSON", "Invalid JSON document", name)


def _decode(store, name, **kwargs):
    return _json(store.read(name), name)


def _schema(name, record, path=None):
    try:
        validate_record(name, record)
    except ArtifactIntegrityError:
        _reject("SCHEMA_INVALID", f"Invalid {name} schema", path)


def _coherence(manifest, command, paths):
    state, eligibility = manifest["state"], manifest["eligibility"]["status"]
    if state == "planned":
        valid = (
            not command["execute"]
            and not command["transfer_completed"]
            and not command["result_verified"]
            and eligibility == "pending"
            and all(
                command[key] is None for key in ("returncode", "timeout_stage", "failure_reason")
            )
        )
    elif state == "completed":
        valid = (
            eligibility == "pending"
            and command["failure_reason"] is None
            and command["timeout_stage"] is None
        )
    else:
        valid = (
            state in ("failed", "interrupted")
            and eligibility == "rejected"
            and command["failure_reason"] is not None
            and not command["result_verified"]
        )
        if (
            state == "failed"
            and command["transfer_completed"]
            and "traffic_summary.json" not in paths
        ):
            valid = False
    if not valid:
        _reject("RESULT_MISMATCH", "Run state and recorded outcome disagree", "command.json")


def _verify(store, cancel=None):
    report = None
    manifest = _decode(store, "manifest.json", limit=1024 * 1024)
    _schema("manifest", manifest)
    # A Phase 1 planned manifest has no Phase 2 evidence to verify.
    if manifest["state"] == "planned" and not manifest["artifacts"]:
        if store.names() != {"manifest.json"}:
            _reject("ARTIFACT_COVERAGE_MISMATCH", "unexpected files in planned run")
        if manifest["eligibility"]["status"] != "pending":
            _reject("RESULT_MISMATCH", "Planned eligibility must be pending", "manifest.json")
        return VerificationResult(True, ("PLANNED_ONLY",), "planned"), None, manifest
    if manifest["state"] == "running" or LOCKS & store.names():
        _reject("RUN_UNFINALIZED", "run has not been finalized")
    checksums = _decode(store, "checksums.json", limit=1024 * 1024)
    _schema("checksums", checksums)
    entries = checksums["files"]
    paths = [entry["path"] for entry in entries]
    manifest_entries = {entry["path"]: entry for entry in manifest["artifacts"]}
    if len(paths) != len(set(paths)) or len(manifest_entries) != len(manifest["artifacts"]):
        _reject("ARTIFACT_COVERAGE_MISMATCH", "duplicate artifact digest entries")
    if set(manifest_entries) != set(paths) | {"checksums.json"}:
        _reject("ARTIFACT_COVERAGE_MISMATCH", "manifest/checksum path coverage differs")
    for entry in entries:
        if store.digest(entry["path"]) != entry or manifest_entries[entry["path"]] != entry:
            _reject("CHECKSUM_MISMATCH", f"artifact digest mismatch: {entry['path']}")
    if store.digest("checksums.json") != manifest_entries["checksums.json"]:
        _reject("CHECKSUM_MISMATCH", "checksums file digest mismatch")
    if store.names() != set(manifest_entries) | {"manifest.json"}:
        _reject("ARTIFACT_COVERAGE_MISMATCH", "unexpected or unlisted files in run")
    _cancel(cancel)
    config_record = _decode(store, "config.json")
    try:
        config = ExperimentConfig.from_dict(config_record)
    except ConfigValidationError:
        _reject("SCHEMA_INVALID", "Recorded configuration is invalid", "config.json")
    if (
        config.sha256 != manifest["config_sha256"]
        or config.data["campaign_id"] != manifest["campaign_id"]
    ):
        _reject("CONFIG_IDENTITY_MISMATCH", "config identity mismatch")
    command = _decode(store, "command.json", limit=1024 * 1024)
    _schema("run_command", command)
    try:
        _phase_scope(config, manifest["run_role"], command["execute"])
    except SafetyPreflightError as exc:
        _reject("RESULT_MISMATCH", f"invalid recorded phase scope: {exc}")
    if config.data["evidence_kind"] != manifest["evidence_kind"]:
        _reject("CONFIG_IDENTITY_MISMATCH", "config evidence kind differs from manifest")
    expected = BASE_PAYLOADS.copy()
    if RAW_PAYLOADS.intersection(paths):
        expected |= RAW_PAYLOADS
    if "traffic_summary.json" in paths:
        expected.add("traffic_summary.json")
    if set(paths) != expected:
        _reject("ARTIFACT_COVERAGE_MISMATCH", "missing required or unexpected payload coverage")
    if command["execute"] is False and (
        manifest["state"] != "planned" or expected != BASE_PAYLOADS
    ):
        _reject("RESULT_MISMATCH", "offline plan is inconsistent with execution artifacts")
    events = [
        _json(line, "events.jsonl")
        for line in store.read("events.jsonl", limit=1024 * 1024).splitlines()
    ]
    if events != manifest["events"]:
        _reject("EVENT_HISTORY_MISMATCH", "manifest event history differs from event artifact")
    if any(event["name"] == "TRAFFIC_STARTED" for event in events) and not RAW_PAYLOADS.issubset(
        paths
    ):
        _reject("RESULT_MISMATCH", "started process is missing raw output artifacts")
    if command["returncode"] is not None and not RAW_PAYLOADS.issubset(paths):
        _reject("RESULT_MISMATCH", "process exit is missing raw output artifacts")
    _coherence(manifest, command, paths)
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
        _reject("RESULT_MISMATCH", "completed run lacks required transfer evidence")
    if "traffic_summary.json" in paths:
        summary = _decode(store, "traffic_summary.json")
        _schema("traffic_summary", summary)
        _decode(store, "client.json")
        raw = store.read("client.json").decode("utf-8")
        _cancel(cancel)
        report = parse_iperf3(
            raw,
            expected_streams=config.data["traffic"]["streams"],
            omit_s=config.data["traffic"]["omit_s"],
        )
        if report.to_dict() != summary["report"]:
            _reject("RESULT_MISMATCH", "traffic summary differs from reconstructed report")
        if not command["execute"] or command["returncode"] != 0 or not completed:
            _reject("RESULT_MISMATCH", "summary is inconsistent with process outcome")
        _traffic_identity(config, command["source_ip"], raw, report)
        reconciled = _report_valid(report)
        if manifest["state"] == "completed" and not reconciled:
            _reject("RESULT_MISMATCH", "completed run has unreconciled traffic result")
        verified = reconciled and manifest["state"] == "completed"
    elif manifest["state"] == "completed":
        _reject("INPUT_MISSING", "completed run lacks traffic summary")
    if type(command.get("result_verified")) is not bool or command["result_verified"] != verified:
        _reject("RESULT_MISMATCH", "recorded verification outcome differs from evidence")
    return VerificationResult(True, (), manifest["state"], completed, verified), report, manifest


def _provenance(store, report, cancel=None):
    """Resolve semantic report fields to raw JSON pointers once, in the verified core."""
    raw = _decode(store, "client.json")
    digest = store.artifacts["client.json"].sha256
    result = {}

    def ref(pointer, source="client", derivation=None, inputs=()):
        return EvidenceReference("client.json", pointer, digest, source, derivation, tuple(inputs))

    def rate(base, source, flows=None):
        if flows is None:
            return (
                ref(
                    base, source, "goodput_bps", [base + "/" + k for k in ("bytes", "start", "end")]
                ),
            )
        return (
            ref(
                base,
                source,
                "AGGREGATE_DERIVED_FROM_FLOWS",
                [flow + "/" + k for flow in flows for k in ("bytes", "start", "end")],
            ),
        )

    source = str(report.receiver_source)
    prefix = "/server_output_json" if source == "embedded_server" else ""
    server = raw.get("server_output_json", raw)
    total = prefix + "/end/sum_received"
    if "sum_received" in server["end"]:
        result["goodput"] = rate(total, source)
    else:
        result["goodput"] = rate(
            prefix + "/end/streams",
            source,
            [prefix + f"/end/streams/{i}/receiver" for i in range(len(report.flows))],
        )
    result["residual"] = (
        ref(
            "/end/sum_sent",
            "client",
            "endpoint_byte_residual",
            ("/end/sum_sent/bytes", prefix + "/end/sum_received/bytes"),
        ),
    )
    if "sum_sent" not in raw["end"] or "sum_received" not in server["end"]:
        result["residual"] = ()
    if "retransmits" in raw["end"].get("sum_sent", {}):
        result["retransmits"] = (ref("/end/sum_sent/retransmits"),)
    else:
        result["retransmits"] = ()
    flow_indices = {item["sender"]["socket"]: i for i, item in enumerate(raw["end"]["streams"])}
    for flow in report.flows:
        _cancel(cancel)
        index = flow_indices[flow.socket_id]
        for label, key in [
            ("mean", "mean_rtt"),
            ("min", "min_rtt"),
            ("max", "max_rtt"),
            ("retransmits", "retransmits"),
        ]:
            result[("flow", flow.socket_id, label)] = (
                (ref(f"/end/streams/{index}/sender/{key}"),)
                if key in raw["end"]["streams"][index]["sender"]
                else ()
            )
    client_tuples = {
        (f.local_host, f.local_port, f.remote_host, f.remote_port): f.socket_id
        for f in report.flows
    }
    lookup = {}
    documents = [("client", "", raw)]
    if "server_output_json" in raw:
        documents.append(("embedded_server", "/server_output_json", raw["server_output_json"]))
    for src, pre, doc in documents:
        ids = {}
        for row in doc["start"]["connected"]:
            identity = tuple(
                row[k]
                for k in (
                    ("local_host", "local_port", "remote_host", "remote_port")
                    if src == "client"
                    else ("remote_host", "remote_port", "local_host", "local_port")
                )
            )
            ids[row["socket"]] = client_tuples[identity]
        for index, epoch in enumerate(doc["intervals"]):
            _cancel(cancel)
            base = pre + f"/intervals/{index}"
            for j, item in enumerate(epoch["streams"]):
                socket_id = ids[item["socket"]]
                key = (src, socket_id, item["start"], item["end"], item["omitted"])
                lookup[key] = (
                    rate(base + f"/streams/{j}", src),
                    (ref(base + f"/streams/{j}/rtt", src),) if "rtt" in item else (),
                )
            aggregate = epoch.get("sum", epoch["streams"][0])
            key = (src, None, aggregate["start"], aggregate["end"], aggregate["omitted"])
            lookup[key] = (
                rate(base + "/sum", src)
                if "sum" in epoch
                else rate(
                    base + "/streams",
                    src,
                    [base + f"/streams/{j}" for j in range(len(epoch["streams"]))],
                ),
                (),
            )
    for i, interval in enumerate(report.intervals):
        key = (
            str(interval.source),
            interval.socket_id,
            interval.start_s,
            interval.end_s,
            interval.omitted,
        )
        goodput, rtt = lookup[key]
        result[("interval", i, "rate")] = goodput
        result[("interval", i, "rtt")] = rtt
    return MappingProxyType(result)


def _inspect(snapshot, cancel=None, *, include_evidence=True):
    manifest = None
    try:
        _cancel(cancel)
        if snapshot.issues:
            issue = snapshot.issues[0]
            raise _InspectionFailure(issue.code, issue.message, issue.path)
        store = _SnapshotStore(snapshot)
        candidate = _decode(store, "manifest.json")
        _schema("manifest", candidate, "manifest.json")
        manifest = candidate
        expected = {item["path"]: item["sha256"] for item in manifest["artifacts"]}
        annotated = []
        for artifact in snapshot.artifacts:
            digest = expected.get(artifact.name)
            status = (
                "unavailable"
                if artifact.data is None
                else "unlisted"
                if digest is None
                else "matched"
                if digest == artifact.sha256
                else "mismatched"
            )
            annotated.append(replace(artifact, expected_sha256=digest, digest_status=status))
        snapshot = replace(snapshot, artifacts=tuple(annotated))
        if not snapshot.finalized or manifest["state"] == "running":
            _reject("RUN_UNFINALIZED", "Run has not been finalized")
        verification, report, manifest = _verify(store, cancel)
        _cancel(cancel)
        evidence = MappingProxyType({})
        if report and include_evidence:
            try:
                evidence = _provenance(store, report, cancel)
            except Exception:
                # Display provenance cannot invalidate independently verified artifacts.
                # Cancellation still takes precedence at the checkpoint below.
                evidence = MappingProxyType({})
        _cancel(cancel)
        return RunInspection(
            snapshot,
            IntegrityStatus.VERIFIED,
            (),
            verification,
            manifest["state"],
            manifest["eligibility"]["status"],
            report,
            freeze(manifest),
            tuple(item for refs in evidence.values() for item in refs),
            evidence,
            failure_reason=(
                _decode(store, "command.json")["failure_reason"]
                if "command.json" in store.artifacts
                else None
            ),
        )
    except (ArtifactIntegrityError, TrafficExecutionError) as exc:
        issue = InspectionIssue(
            InspectionCode.RESULT_MISMATCH,
            None,
            f"Invalid recorded traffic result ({type(exc).__name__})",
        )
    except _InspectionFailure as exc:
        issue = exc.issue
    status = {
        "CANCELLED": IntegrityStatus.CANCELLED,
        "RUN_UNFINALIZED": IntegrityStatus.UNFINALIZED,
    }.get(issue.code, IntegrityStatus.FAILED)
    return RunInspection(
        replace(snapshot, finalized=False) if status == "unfinalized" else snapshot,
        status,
        (issue,),
        state=manifest["state"] if manifest else None,
        eligibility=manifest["eligibility"]["status"] if manifest else None,
        manifest=freeze(manifest) if manifest else None,
    )


def inspect_snapshot(snapshot: RunSnapshot) -> RunInspection:
    return _inspect(snapshot)


def load_run(
    path: Path,
    *,
    cancel: Event | None = None,
    progress: Callable[[int, int], None] | None = None,
    include_evidence: bool = True,
) -> RunInspection:
    snapshot = RunSnapshot(Path(path), (), (), (), False)
    try:
        snapshot = capture_run(path, cancel=cancel, progress=progress)
        return _inspect(snapshot, cancel, include_evidence=include_evidence)
    except Exception:
        issue = InspectionIssue(
            InspectionCode.INTERNAL_ERROR, None, "Unexpected inspection failure"
        )
        return RunInspection(snapshot, IntegrityStatus.FAILED, (issue,))
