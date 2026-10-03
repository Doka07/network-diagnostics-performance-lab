"""Operator-only receiver shutdown; no implicit SSH configuration or traffic."""

from __future__ import annotations

import base64
import hashlib
import math
import os
import signal
import subprocess
import threading
import time
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from diaglab.artifacts.store import ArtifactStore
from diaglab.serialization import parse_json

OUTPUT_LIMIT = 8 * 1024 * 1024
REQUIRED = ("owner.json", "server.jsonl", "server.stderr", "cleanup.json")


@dataclass
class Session:
    process: subprocess.Popen
    buffers: dict[str, bytearray]
    threads: tuple[threading.Thread, ...]
    overflow: threading.Event


def _argv(argv):
    if (
        not isinstance(argv, list)
        or not argv
        or any(not isinstance(item, str) or not item or "\0" in item for item in argv)
    ):
        raise ValueError("command must be a nonempty argument vector")


def start_session(argv: list[str]) -> Session:
    """Own the new session and drain both pipes without unbounded buffering."""
    _argv(argv)
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    overflow = threading.Event()

    def drain(name, pipe):
        with pipe:
            while chunk := pipe.read(65536):
                remaining = OUTPUT_LIMIT - len(buffers[name])
                buffers[name].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    overflow.set()

    threads = tuple(
        threading.Thread(target=drain, args=(name, getattr(process, name)), daemon=True)
        for name in buffers
    )
    for thread in threads:
        thread.start()
    return Session(process, buffers, threads, overflow)


def _alive(session):
    session.process.poll()
    try:
        os.killpg(session.process.pid, 0)
        return True
    except ProcessLookupError:
        return False


def _reap(session, grace):
    """Signal only the session created by start_session, including remaining children."""
    import time

    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not _alive(session):
            break
        try:
            os.killpg(session.process.pid, sig)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + grace
        while _alive(session) and time.monotonic() < deadline:
            time.sleep(0.02)
    session.process.wait(timeout=grace)
    for thread in session.threads:
        thread.join(timeout=grace)
    return not _alive(session) and not any(t.is_alive() for t in session.threads)


def finish_session(
    session: Session,
    *,
    stop_argv: list[str],
    cleanup_argv: list[str],
    capture_argv: list[str],
    output: Path,
    traffic_failure: str | None = None,
    shutdown_timeout: float = 30,
    command_timeout: float = 60,
    terminate_grace: float = 2,
) -> dict:
    """Complete independent cleanup/capture steps despite earlier lifecycle failures."""
    for value in (shutdown_timeout, command_timeout, terminate_grace):
        if type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
            raise ValueError("timeouts must be positive finite seconds")
    for command in (stop_argv, cleanup_argv, capture_argv):
        _argv(command)
    if traffic_failure is not None and not isinstance(traffic_failure, str):
        raise ValueError("traffic_failure must be text or null")
    result = {
        "schema_version": "1.0",
        "traffic_failure": traffic_failure,
        "lifecycle_errors": [],
        "cleanup_verified": False,
        "evidence_verified": False,
        "local_session_reaped": False,
        "commands": {},
        "missing_files": [],
        "session_wait_s": 0.0,
    }
    errors = result["lifecycle_errors"]

    with ExitStack() as stack:
        try:
            store = stack.enter_context(ArtifactStore(output, create=True))
        except Exception:
            store = None
            errors.append("OUTPUT_UNAVAILABLE")

        def record(code):
            if code not in errors:
                errors.append(code)

        def persist(name, data):
            try:
                store.write(name, data)
            except Exception:
                record("EVIDENCE_WRITE_FAILED")

        def invoke(label, command):
            child = None
            started = time.monotonic()
            meta = {
                "returncode": None,
                "timed_out": False,
                "output_overflow": False,
                "started_utc": datetime.now(UTC).isoformat(),
                "duration_s": 0.0,
            }
            result["commands"][label] = meta
            try:
                child = start_session(command)
                child.process.wait(timeout=command_timeout)
            except subprocess.TimeoutExpired:
                meta["timed_out"] = True
                record(label.upper() + "_TIMEOUT")
            except KeyboardInterrupt:
                record(label.upper() + "_INTERRUPTED")
            except Exception:
                record(label.upper() + "_FAILED")
            finally:
                if child is not None:
                    try:
                        if not _reap(child, terminate_grace):
                            record(label.upper() + "_LOCAL_CLEANUP_FAILED")
                    except (Exception, KeyboardInterrupt):
                        record(label.upper() + "_LOCAL_CLEANUP_FAILED")
                    meta["returncode"] = child.process.poll()
                    meta["output_overflow"] = child.overflow.is_set()
                    if meta["returncode"] != 0:
                        record(label.upper() + "_NONZERO")
                    if meta["output_overflow"]:
                        record(label.upper() + "_OUTPUT_OVERFLOW")
                    for name, data in child.buffers.items():
                        persist(f"{label}.{name}", bytes(data))
                meta["duration_s"] = time.monotonic() - started
            if (
                child is None
                or meta["returncode"] != 0
                or meta["timed_out"]
                or meta["output_overflow"]
            ):
                return None
            return bytes(child.buffers["stdout"])

        invoke("stop", stop_argv)
        wait_started = time.monotonic()
        try:
            session.process.wait(timeout=shutdown_timeout)
        except subprocess.TimeoutExpired:
            record("SESSION_WAIT_TIMEOUT")
        except KeyboardInterrupt:
            record("SESSION_WAIT_INTERRUPTED")
        except Exception:
            record("SESSION_WAIT_FAILED")
        finally:
            result["session_wait_s"] = time.monotonic() - wait_started
            try:
                result["local_session_reaped"] = _reap(session, terminate_grace)
            except (Exception, KeyboardInterrupt):
                record("SESSION_LOCAL_CLEANUP_FAILED")
            if not result["local_session_reaped"]:
                record("SESSION_LOCAL_CLEANUP_FAILED")
            if session.process.poll() != 0:
                record("SESSION_NONZERO")
            if session.overflow.is_set():
                record("SESSION_OUTPUT_OVERFLOW")
            for name, data in session.buffers.items():
                persist(f"session.{name}", bytes(data))

        cleanup = invoke("cleanup", cleanup_argv)
        try:
            status = parse_json(cleanup.decode("utf-8-sig")) if cleanup else None
            result["cleanup_verified"] = (
                isinstance(status, dict)
                and set(status) == {"process_gone", "listener_gone", "rule_gone"}
                and all(value is True for value in status.values())
            )
        except Exception:
            pass
        if not result["cleanup_verified"]:
            record("CLEANUP_UNVERIFIED")

        captured = invoke("capture", capture_argv)
        try:
            payload = parse_json(captured.decode("utf-8-sig")) if captured else None
            if not isinstance(payload, dict) or set(payload) != {
                "files",
                "manifest",
                "missing_files",
            }:
                raise ValueError("capture envelope")
            files = payload["files"]
            if not isinstance(files, dict) or not set(files) <= set(REQUIRED):
                raise ValueError("unknown evidence files")
            missing = sorted(set(REQUIRED) - set(files))
            result["missing_files"] = missing
            if sorted(payload["missing_files"]) != missing:
                raise ValueError("missing-file inventory mismatch")
            manifest = payload["manifest"]
            if not isinstance(manifest, dict) or set(manifest) != {"files"}:
                raise ValueError("manifest shape")
            entries = {entry["path"]: entry for entry in manifest["files"]}
            if len(entries) != len(manifest["files"]) or set(entries) != set(files):
                raise ValueError("manifest inventory mismatch")
            for name, encoded in files.items():
                data = base64.b64decode(encoded, validate=True)
                entry = entries[name]
                if set(entry) != {"path", "size_bytes", "sha256"} or (
                    type(entry["size_bytes"]) is not int
                    or entry["size_bytes"] != len(data)
                    or entry["sha256"] != hashlib.sha256(data).hexdigest()
                ):
                    raise ValueError("evidence digest mismatch")
                persist("receiver-" + name, data)
            if store is not None:
                store.write_json("receiver-manifest.json", manifest)
            result["evidence_verified"] = not missing and "EVIDENCE_WRITE_FAILED" not in errors
            if missing:
                record("RECEIVER_EVIDENCE_MISSING")
        except Exception:
            record("CAPTURE_INVALID")
        if store is not None:
            try:
                store.write_json("lifecycle.json", result)
                store.write_json(
                    "checksums.json",
                    {
                        "schema_version": "1.0",
                        "files": [
                            store.digest(name)
                            for name in sorted(store.names())
                            if name != ".run.lock"
                        ],
                    },
                )
            except Exception:
                record("FINAL_RECORD_WRITE_FAILED")
    return result
