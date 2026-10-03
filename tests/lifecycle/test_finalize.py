"""FZ-01–09: contract-first regressions for the proposed operator finalizer (Claude's
2026-10-03 review, "E1/E2 finalization"), written before any implementation exists.

E1 skipped verify/export/SHA256SUMS behind an `assert` on lifecycle success; E2 aborted at
an independent absence query that timed out; the no-probe run stored a readiness exception
(with full SSH argv) in `traffic_failure`. Each was hand-finalized minutes later. These
tests pin a repository-owned replacement. Proposed API (binding unless Denis rules
otherwise; details recorded as FZ-n in Claude's canonical review):

    scripts.diagnostic_finalize.finalize_diagnostic(
        root, *, traffic, operator_failures, lifecycle, checks, check_timeout=60) -> dict

traffic: None (never attempted) or {"started": bool, "failure": str | None}.
operator_failures: codes observed before finalization (e.g. READINESS_TIMEOUT).
lifecycle: the finish_session record, verbatim, or None if it never ran.
checks: ordered {name: argv} run sequentially, each bounded by check_timeout.
Writes root/finalization/<name>.stdout|.stderr, root/operator-status.json (equal to the
returned record), then root/SHA256SUMS last (sha256sum format, every regular file under
root except itself). Never raises for check, write or seal failures; invalid arguments
raise ValueError before anything is run or written.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

from .conftest import REPO

CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
UTC = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|\+00:00)")
LIFECYCLE_FAILED = {
    "schema_version": "1.0",
    "traffic_failure": "EXECUTION_DEADLINE_EXCEEDED",
    "lifecycle_errors": ["SESSION_WAIT_TIMEOUT", "CLEANUP_TIMEOUT", "CLEANUP_UNVERIFIED"],
    "cleanup_verified": False,
    "evidence_verified": True,
    "local_session_reaped": True,
    "commands": {"cleanup": {"returncode": 255, "timed_out": True, "output_overflow": False}},
    "missing_files": [],
}
LIFECYCLE_CLEAN = {
    **LIFECYCLE_FAILED,
    "lifecycle_errors": [],
    "cleanup_verified": True,
    "commands": {"cleanup": {"returncode": 0, "timed_out": False, "output_overflow": False}},
}


def finalizer():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    return importlib.import_module("scripts.diagnostic_finalize")


def check(kind: str, marker: Path | None = None) -> list[str]:
    """Fake post-run checks. Each appends its name to a shared log when it starts."""
    log = f"open({str(marker)!r}, 'a').write({kind!r} + chr(10))" if marker else "pass"
    body = {
        "ok": 'print(\'{"listener_gone": true, "rule_gone": true}\')',
        "fail": "import sys; print('partial-fail'); sys.exit(2)",
        "hang": "import sys, time; print('partial-before-hang', flush=True); time.sleep(60)",
    }[kind]
    return [sys.executable, "-c", f"{log}\n{body}"]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    run = tmp_path / "diagnostic-x"
    (run / "run-1").mkdir(parents=True)
    (run / "run-1" / "client.json").write_text('{"raw": true}')
    (run / "operator.py").write_text("# operator copy")
    return run


def finalize(root: Path, **kwargs) -> dict:
    kwargs.setdefault("traffic", {"started": True, "failure": "EXECUTION_DEADLINE_EXCEEDED"})
    kwargs.setdefault("operator_failures", [])
    kwargs.setdefault("lifecycle", LIFECYCLE_FAILED)
    kwargs.setdefault("checks", {"absence": check("ok"), "verify": check("ok")})
    kwargs.setdefault("check_timeout", 5.0)
    return finalizer().finalize_diagnostic(root, **kwargs)


def sums(root: Path) -> dict[str, str]:
    lines = (root / "SHA256SUMS").read_text().splitlines()
    return {line[66:]: line[:64] for line in lines}


def files_under(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# ---------------------------------------------------------------- FZ-01 always attempts


def test_fz01_every_check_runs_after_earlier_failures_and_timeouts(root) -> None:
    log = root.parent / "order.log"
    checks = {
        "absence": check("hang", log),  # the E2 failure: independent query times out
        "provenance": check("fail", log),
        "verify": check("ok", log),
        "export": check("ok", log),
    }
    started = time.monotonic()
    record = finalize(root, checks=checks, check_timeout=1.0)
    assert time.monotonic() - started < 15  # hang bounded by check_timeout
    assert log.read_text().split() == ["hang", "fail", "ok", "ok"]  # all, in order
    assert record["checks"]["absence"]["timed_out"] is True
    assert record["checks"]["provenance"]["returncode"] == 2
    assert record["checks"]["verify"]["returncode"] == 0
    assert record["checks"]["export"]["returncode"] == 0
    failures = record["operator_failures"]
    assert any("ABSENCE" in code for code in failures)
    assert any("PROVENANCE" in code for code in failures)
    assert not any("VERIFY" in code or "EXPORT" in code for code in failures)
    assert all(CODE.fullmatch(code) for code in failures)
    assert record["diagnostic_complete"] is False


def test_fz01_missing_executable_is_a_recorded_failure_not_an_exception(root) -> None:
    record = finalize(root, checks={"verify": [str(root / "no-such-binary")], "x": check("ok")})
    assert any("VERIFY" in code for code in record["operator_failures"])
    assert record["checks"]["x"]["returncode"] == 0
    assert record["sealed"] is True


# --------------------------------------------------------------------- FZ-02 always seals


@pytest.mark.parametrize("scenario", ["clean", "lifecycle_failed", "checks_failed", "no_lifecycle"])
def test_fz02_seal_is_written_last_and_covers_everything(root, scenario) -> None:
    kwargs = {
        "clean": {"lifecycle": LIFECYCLE_CLEAN},
        "lifecycle_failed": {},
        "checks_failed": {"checks": {"absence": check("fail"), "verify": check("hang")}},
        "no_lifecycle": {"lifecycle": None},
    }[scenario]
    record = finalize(root, check_timeout=1.0, **kwargs)
    assert record["sealed"] is True
    listed = sums(root)
    assert set(listed) == files_under(root) - {"SHA256SUMS"}
    for name, digest in listed.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
    assert "operator-status.json" in listed  # the status itself is sealed
    assert any(name.startswith("finalization/") for name in listed)
    lines = (root / "SHA256SUMS").read_text().splitlines()
    assert lines == sorted(lines, key=lambda line: line[66:])
    status = (root / "operator-status.json").stat().st_mtime_ns
    assert status <= (root / "SHA256SUMS").stat().st_mtime_ns
    result = subprocess.run(["sha256sum", "-c", "--quiet", "SHA256SUMS"], cwd=root)
    assert result.returncode == 0  # standard tool can verify it


def test_fz02_status_file_equals_returned_record(root) -> None:
    record = finalize(root)
    assert json.loads((root / "operator-status.json").read_text()) == record


# ------------------------------------------------- FZ-03 traffic vs operator failure fields


def test_fz03_operator_failure_never_lands_in_traffic_failure(root) -> None:
    """The no-probe case: readiness timed out, no client ran."""
    record = finalize(
        root,
        traffic=None,
        operator_failures=["READINESS_TIMEOUT"],
        lifecycle=LIFECYCLE_CLEAN,
    )
    assert record["traffic_started"] is False
    assert record["traffic_failure"] is None
    assert "READINESS_TIMEOUT" in record["operator_failures"]
    assert record["diagnostic_complete"] is False


@pytest.mark.parametrize("failure", [None, "EXECUTION_DEADLINE_EXCEEDED", 'ünïcode "q"\n'])
def test_fz03_traffic_failure_is_preserved_verbatim(root, failure) -> None:
    traffic = {"started": True, "failure": failure}
    record = finalize(root, traffic=traffic, operator_failures=["X_Y"])
    assert record["traffic_started"] is True
    assert record["traffic_failure"] == failure
    assert "X_Y" in record["operator_failures"] and "X_Y" != record["traffic_failure"]


def test_fz03_traffic_failure_without_traffic_is_refused(root) -> None:
    with pytest.raises(ValueError):
        finalize(root, traffic={"started": False, "failure": "EXECUTION_DEADLINE_EXCEEDED"})
    assert not (root / "SHA256SUMS").exists()


# --------------------------------------------------------- FZ-04 lifecycle stays immutable


def test_fz04_later_successful_checks_never_rewrite_the_lifecycle_record(root) -> None:
    original = json.loads(json.dumps(LIFECYCLE_FAILED))
    record = finalize(root, checks={"absence": check("ok")})
    assert record["lifecycle"] == original  # cleanup_verified stays False
    assert LIFECYCLE_FAILED == original  # the caller's dict was not mutated either
    assert record["diagnostic_complete"] is False


def test_fz04_missing_lifecycle_is_explicit(root) -> None:
    record = finalize(root, lifecycle=None, checks={"absence": check("ok")})
    assert record["lifecycle"] is None
    assert any("LIFECYCLE" in code for code in record["operator_failures"])
    assert record["diagnostic_complete"] is False


def test_fz04_complete_only_when_everything_succeeded(root) -> None:
    record = finalize(root, lifecycle=LIFECYCLE_CLEAN, traffic={"started": True, "failure": None})
    assert record["operator_failures"] == []
    assert record["diagnostic_complete"] is True


# --------------------------------------------------- FZ-05 partial output and timing kept


def test_fz05_partial_output_of_a_timed_out_check_is_kept(root) -> None:
    finalize(root, checks={"absence": check("hang")}, check_timeout=1.0)
    assert "partial-before-hang" in (root / "finalization" / "absence.stdout").read_text()


def test_fz05_each_check_records_when_it_ran_and_how_long(root) -> None:
    record = finalize(root, checks={"a": check("ok"), "b": check("hang")}, check_timeout=1.0)
    for name in ("a", "b"):
        entry = record["checks"][name]
        assert UTC.fullmatch(entry["started_utc"]), entry["started_utc"]
        assert isinstance(entry["duration_s"], float) and entry["duration_s"] >= 0
    assert 0.9 <= record["checks"]["b"]["duration_s"] < 10
    assert record["checks"]["a"]["started_utc"] <= record["checks"]["b"]["started_utc"]


# ------------------------------------------------------- FZ-06 never overwrites, no raise


def test_fz06_existing_seal_or_status_is_never_overwritten(root) -> None:
    (root / "SHA256SUMS").write_text("original seal\n")
    (root / "operator-status.json").write_text('{"original": true}')
    record = finalize(root)
    assert (root / "SHA256SUMS").read_text() == "original seal\n"
    assert (root / "operator-status.json").read_text() == '{"original": true}'
    assert record["sealed"] is False
    assert record["operator_failures"]


def test_fz06_unwritable_root_returns_a_record_instead_of_raising(tmp_path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    record = finalize(blocker / "run")
    assert record["sealed"] is False
    assert record["operator_failures"]


# --------------------------------------------------------------- FZ-07 argument validation


@pytest.mark.parametrize(
    "kwargs",
    [
        {"check_timeout": 0},
        {"check_timeout": -1},
        {"check_timeout": math.inf},
        {"check_timeout": math.nan},
        {"checks": {"Bad Name": check("ok")}},
        {"checks": {"../escape": check("ok")}},
        {"checks": {"ok": "not an argv"}},
        {"operator_failures": ["not a code"]},
    ],
)
def test_fz07_invalid_arguments_raise_before_anything_runs(root, kwargs) -> None:
    before = files_under(root)
    with pytest.raises(ValueError):
        finalize(root, **kwargs)
    assert files_under(root) == before


# ------------------------------------------------------ FZ-08 no assert-based control flow


def test_fz08_behaviour_is_identical_under_python_optimize(root, tmp_path) -> None:
    """E1/E2 gated finalization on `assert`; `python -O` strips asserts. The finalizer
    must not depend on them: the same failing inputs give the same record under -O."""
    script = tmp_path / "run_finalize.py"
    script.write_text(
        "import json, sys\n"
        f"sys.path.insert(0, {str(REPO)!r})\n"
        "from scripts.diagnostic_finalize import finalize_diagnostic\n"
        "record = finalize_diagnostic(\n"
        f"    __import__('pathlib').Path({str(root)!r}),\n"
        "    traffic={'started': True, 'failure': 'EXECUTION_DEADLINE_EXCEEDED'},\n"
        "    operator_failures=['READINESS_TIMEOUT'],\n"
        f"    lifecycle={LIFECYCLE_FAILED!r},\n"
        f"    checks={{'verify': {check('fail')!r}}},\n"
        "    check_timeout=5.0)\n"
        "print(json.dumps({k: record[k] for k in ('operator_failures', 'sealed', "
        "'diagnostic_complete', 'traffic_failure')}))\n"
    )
    out = subprocess.run(
        [sys.executable, "-O", str(script)], capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr
    summary = json.loads(out.stdout)
    assert summary["sealed"] is True and summary["diagnostic_complete"] is False
    assert "READINESS_TIMEOUT" in summary["operator_failures"]
    assert summary["traffic_failure"] == "EXECUTION_DEADLINE_EXCEEDED"


# -------------------------------------------- FZ-09 lifecycle per-step timing (LR-8 proposal)


def test_fz09_lifecycle_commands_record_start_time_and_duration(harness) -> None:
    """E1/E2 recorded SESSION_WAIT_TIMEOUT/CLEANUP_TIMEOUT without durations, so the
    timeouts could not be located in time. Proposed additive LR-8: each `commands` entry
    gains started_utc and duration_s, and the record gains session_wait_s."""
    record = harness.finish(harness.start("stall"), cleanup="hang", command_timeout=1.0)
    for name in ("stop", "cleanup", "capture"):
        entry = record["commands"][name]
        assert isinstance(entry["started_utc"], str) and entry["started_utc"]
        assert isinstance(entry["duration_s"], float) and entry["duration_s"] >= 0
    assert 0.9 <= record["commands"]["cleanup"]["duration_s"] < 10
    assert isinstance(record["session_wait_s"], float) and record["session_wait_s"] >= 0.9
