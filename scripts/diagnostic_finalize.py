"""Bounded post-run checks and immutable diagnostic sealing (operator-only)."""

from __future__ import annotations

import copy
import math
import os
import re
import stat
import subprocess
import time
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from diaglab.artifacts.checksums import artifact_digest
from diaglab.artifacts.store import ArtifactStore
from scripts.receiver_lifecycle import _argv, _reap, start_session


def _validate(traffic, operator_failures, lifecycle, checks, timeout):
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive finite seconds")
    if traffic is not None and (
        not isinstance(traffic, dict)
        or set(traffic) != {"started", "failure"}
        or type(traffic["started"]) is not bool
        or (traffic["failure"] is not None and not isinstance(traffic["failure"], str))
        or (not traffic["started"] and traffic["failure"] is not None)
    ):
        raise ValueError("traffic must describe an attempted traffic operation")
    if not isinstance(operator_failures, list) or any(
        not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", code)
        for code in operator_failures
    ):
        raise ValueError("operator failures must be UPPER_SNAKE codes")
    if lifecycle is not None and not isinstance(lifecycle, dict):
        raise ValueError("lifecycle must be a record or null")
    if not isinstance(checks, dict):
        raise ValueError("checks must be an ordered mapping")
    for name, command in checks.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9_-]+", name):
            raise ValueError("check name must match [a-z0-9_-]+")
        _argv(command)


def _seal_lines(root):
    names = []
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if not stat.S_ISDIR(mode) and not stat.S_ISREG(mode):
                raise ValueError("nonregular diagnostic artifact")
        for name in files:
            relative = (Path(directory) / name).relative_to(root).as_posix()
            if relative == "SHA256SUMS":
                continue
            if any(char in relative for char in "\n\r\\"):
                raise ValueError("ambiguous checksum filename")
            names.append(relative)
    return "".join(
        f"{artifact_digest(root, name)['sha256']}  {name}\n" for name in sorted(names)
    ).encode()


def finalize_diagnostic(
    root,
    *,
    traffic,
    operator_failures,
    lifecycle,
    checks,
    check_timeout=60,
) -> dict:
    """Attempt every check, preserving failures; seal last without overwriting evidence.

    Invalid inputs raise before execution. Runtime failures return an authoritative
    record; if persistence fails, callers must retain that record outside the bundle.
    A completed diagnostic need not be a successful traffic experiment.
    """
    _validate(traffic, operator_failures, lifecycle, checks, check_timeout)
    result = {
        "schema_version": "1.0",
        "traffic_started": bool(traffic and traffic["started"]),
        "traffic_failure": traffic["failure"] if traffic else None,
        "operator_failures": list(operator_failures),
        "lifecycle": copy.deepcopy(lifecycle),
        "checks": {},
        "diagnostic_complete": False,
        "sealed": False,
    }

    def fail(code):
        if code not in result["operator_failures"]:
            result["operator_failures"].append(code)

    clean = (
        lifecycle is not None
        and not lifecycle.get("lifecycle_errors", [])
        and all(
            lifecycle.get(key) is True
            for key in ("cleanup_verified", "evidence_verified", "local_session_reaped")
        )
    )
    if lifecycle is None:
        fail("LIFECYCLE_NOT_RUN")
    elif not clean:
        fail("LIFECYCLE_ERRORS")

    with ExitStack() as stack:
        store = outputs = None
        try:
            root = Path(root).absolute()
            store = stack.enter_context(ArtifactStore(root))
            if {"SHA256SUMS", "operator-status.json"} & set(os.listdir(store.directory)):
                fail("EXISTING_FINALIZATION")
                return result
            os.mkdir("finalization", mode=0o700, dir_fd=store.directory)
            outputs = stack.enter_context(ArtifactStore(root / "finalization"))
        except Exception:
            fail("OUTPUT_UNAVAILABLE")

        for name, command in checks.items():
            prefix = name.upper().replace("-", "_")
            if not prefix[0].isalpha():
                prefix = "CHECK_" + prefix
            prefix = prefix[:40]
            started = time.monotonic()
            meta = {
                "started_utc": datetime.now(UTC).isoformat(),
                "duration_s": 0.0,
                "returncode": None,
                "timed_out": False,
                "output_overflow": False,
            }
            result["checks"][name] = meta
            child = None
            error_text = b""
            try:
                child = start_session(command)
                child.process.wait(timeout=check_timeout)
            except subprocess.TimeoutExpired:
                meta["timed_out"] = True
                fail(prefix + "_TIMEOUT")
            except (Exception, KeyboardInterrupt) as exc:
                error_text = (type(exc).__name__ + ": " + str(exc)).encode()
                fail(prefix + "_FAILED")
            finally:
                if child is not None:
                    try:
                        if not _reap(child, 0.5):
                            fail(prefix + "_LOCAL_CLEANUP_FAILED")
                    except (Exception, KeyboardInterrupt):
                        fail(prefix + "_LOCAL_CLEANUP_FAILED")
                    meta["returncode"] = child.process.poll()
                    meta["output_overflow"] = child.overflow.is_set()
                    if meta["returncode"] != 0:
                        fail(prefix + "_NONZERO")
                    if meta["output_overflow"]:
                        fail(prefix + "_OUTPUT_OVERFLOW")
                meta["duration_s"] = time.monotonic() - started
                for stream in ("stdout", "stderr"):
                    data = bytes(child.buffers[stream]) if child else b""
                    if stream == "stderr":
                        data += error_text
                    try:
                        if outputs is None:
                            raise OSError("no diagnostic output directory")
                        outputs.write(f"{name}.{stream}", data)
                    except Exception:
                        fail("EVIDENCE_WRITE_FAILED")

        result["diagnostic_complete"] = bool(clean and not result["operator_failures"])
        try:
            if store is None:
                raise OSError("no diagnostic root")
            result["sealed"] = True
            store.write_json("operator-status.json", result)
            store.write("SHA256SUMS", _seal_lines(root))
        except (Exception, KeyboardInterrupt):
            result["sealed"] = False
            result["diagnostic_complete"] = False
            fail("SEAL_FAILED")
    return result
