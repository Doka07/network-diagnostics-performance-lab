"""Contract-first regressions for audit findings AUD-01..AUD-03 (docs/HANDOFF.md, 2026-10-01).

Written from docs/PHASE2_CONTRACTS.md and the audit statement before Codex's production
fixes; the expected behavior is the contract's, not the current implementation's. They
use the accepted Phase 2 runner with a local mock iperf3; no network activity occurs.

AUD-01: the executed traffic child must not inherit blocked SIGINT/SIGTERM. Ordinary
        SIGTERM-responsive children must end on SIGTERM; only children that ignore SIGTERM
        are escalated to SIGKILL.
AUD-02: verify requires outcome coherence for every recorded state (R-26), while
        legitimate planned/failed/interrupted/completed evidence still verifies.
AUD-03: invalid recorded configuration is an artifact-integrity failure (verify exit 3),
        while `diaglab config validate` keeps exit 1 for invalid configuration files.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
import yaml

from diaglab.config import ExperimentConfig
from diaglab.exceptions import ArtifactIntegrityError, TrafficExecutionError
from diaglab.run import RunInterrupted, run_experiment, verify_run
from diaglab.traffic import runner as runner_module
from diaglab.traffic.runner import Iperf3TrafficAdapter

from .runs import (
    SOURCE_IP,
    RunBuilder,
    captured_text,
    cli_verify,
    config_dict,
    edit_json,
    rehash,
)

TERMINATION = (signal.SIGINT, signal.SIGTERM)

# --------------------------------------------------------------------------- AUD-01


@pytest.fixture
def live(tmp_path: Path, base_config: dict, monkeypatch: pytest.MonkeyPatch):
    """Run run_experiment(execute=True) against the mock with given behavior/timeouts."""
    builder = RunBuilder(tmp_path / "aud01", base_config)
    monkeypatch.setattr(runner_module, "resolve_source", lambda context: SOURCE_IP)
    monkeypatch.setattr(runner_module, "probe_server", lambda context, source: None)
    document = tmp_path / "success.json"
    document.write_text(captured_text("single_stream_success_client.json"), encoding="utf-8")

    def run(
        name: str,
        *,
        behavior: str | None = None,
        duration_s: float = 30,
        traffic: dict[str, Any] | None = None,
    ) -> tuple[Path, Path, float, BaseException | None]:
        report = tmp_path / f"{name}.signals.json"
        monkeypatch.setenv("MOCK_DOC", str(document))
        monkeypatch.setenv("MOCK_RC", "0")
        monkeypatch.setenv("MOCK_SIGNAL_REPORT", str(report))
        if behavior is None:
            monkeypatch.delenv("MOCK_BEHAVIOR", raising=False)
        else:
            monkeypatch.setenv("MOCK_BEHAVIOR", behavior)
        data = config_dict(base_config, duration_s=duration_s, streams=1)
        data["traffic"].update(traffic or {})
        config = ExperimentConfig.from_dict(data)
        output = tmp_path / name
        started = time.monotonic()
        raised: BaseException | None = None
        try:
            run_experiment(config, output, execute=True, executable=str(builder.mock))
        except (TrafficExecutionError, RunInterrupted) as exc:
            raised = exc
        return output, report, time.monotonic() - started, raised

    return run


def _bit(signum: int) -> int:
    return 1 << (int(signum) - 1)


def test_aud01_executed_child_does_not_inherit_blocked_termination_signals(live) -> None:
    output, report, _, raised = live("success")
    assert raised is None
    assert verify_run(output).state == "completed"
    state = json.loads(report.read_text())
    for signum in TERMINATION:
        assert int(signum) not in state["pthread_sigmask"], state
        if "SigBlk" in state:
            assert not state["SigBlk"] & _bit(signum), f"{signum!r} blocked in child"
        if "SigIgn" in state:
            assert not state["SigIgn"] & _bit(signum), f"{signum!r} ignored in child"


def test_aud01_parent_signal_mask_is_restored_after_start(live) -> None:
    live("success")
    blocked = signal.pthread_sigmask(signal.SIG_BLOCK, [])
    assert not set(TERMINATION) & set(blocked)


DEADLINE_TIMEOUTS = {
    "connect_timeout_s": 0.2,
    "finish_timeout_s": 0.2,
    "terminate_grace_s": 3.0,
}


def test_aud01_sigterm_responsive_child_ends_on_sigterm_at_deadline(live) -> None:
    output, report, elapsed, raised = live(
        "deadline", behavior="hang", duration_s=0.3, traffic=DEADLINE_TIMEOUTS
    )
    assert isinstance(raised, TrafficExecutionError)
    command = json.loads((output / "command.json").read_text())
    assert command["failure_reason"] == "EXECUTION_DEADLINE_EXCEEDED"
    # Default SIGTERM disposition: terminated by SIGTERM, never escalated to SIGKILL.
    assert command["returncode"] == -signal.SIGTERM, command
    # With the signal blocked the child would survive the whole 3 s grace before SIGKILL.
    assert elapsed < 2.5, f"took {elapsed:.2f}s: SIGTERM was not delivered promptly"
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["cleanup"]["status"] == "verified"
    assert json.loads(report.read_text())["pthread_sigmask"] == []
    assert verify_run(output).verified is True


def test_aud01_sigterm_responsive_child_ends_on_sigterm_after_interruption(
    live, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_start = Iperf3TrafficAdapter.start

    def start_then_interrupt(adapter: Iperf3TrafficAdapter, context: Any) -> Any:
        handle = original_start(adapter, context)
        os.kill(os.getpid(), signal.SIGINT)
        return handle

    monkeypatch.setattr(Iperf3TrafficAdapter, "start", start_then_interrupt)
    output, _, elapsed, raised = live(
        "interrupted", behavior="hang", duration_s=20, traffic=DEADLINE_TIMEOUTS
    )
    assert isinstance(raised, RunInterrupted)
    command = json.loads((output / "command.json").read_text())
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["state"] == "interrupted"
    assert manifest["cleanup"]["status"] == "verified"
    assert command["returncode"] == -signal.SIGTERM, command
    assert elapsed < 2.5, f"took {elapsed:.2f}s: SIGTERM was not delivered promptly"


def test_aud01_sigterm_ignoring_child_is_still_escalated_to_sigkill(live) -> None:
    output, report, _, raised = live(
        "ignoring",
        behavior="ignore_sigterm",
        duration_s=0.3,
        traffic={**DEADLINE_TIMEOUTS, "terminate_grace_s": 0.3},
    )
    assert isinstance(raised, TrafficExecutionError)
    command = json.loads((output / "command.json").read_text())
    manifest = json.loads((output / "manifest.json").read_text())
    assert command["returncode"] == -signal.SIGKILL, command
    assert manifest["cleanup"]["status"] == "verified"
    # The child itself chose SIG_IGN after start; it did not inherit a blocked mask.
    assert json.loads(report.read_text())["pthread_sigmask"] == []


# --------------------------------------------------------------------------- AUD-02


LEGITIMATE = [
    "offline_plan",
    "phase1_manifest",
    "captured_success",
    "connection_timeout",
    "no_server",
    "gap",
    "interrupted",
    "four_omit",
]


@pytest.mark.parametrize("name", LEGITIMATE)
def test_aud02_legitimate_evidence_still_verifies(fresh, name) -> None:
    run = fresh(name)
    result = verify_run(run)
    assert result.verified is True
    assert cli_verify(run) == 0


def _command(**changes: Any):
    def apply(run: Path) -> None:
        edit_json(run, "command.json", lambda record: record.update(changes))
        rehash(run)

    return apply


def _eligibility(status: str, reasons: list[str] | None = None):
    def apply(run: Path) -> None:
        def change(manifest: dict) -> None:
            manifest["eligibility"] = {
                "status": status,
                "reasons": manifest["eligibility"]["reasons"] if reasons is None else reasons,
            }

        edit_json(run, "manifest.json", change)
        rehash(run)

    return apply


# Coherence rules (R-26) per recorded state; each row is a contradiction that must fail.
INCOHERENT = [
    # planned: nothing executed, so no outcome may be claimed (the reproduced AUD-02 case).
    ("offline_plan", "transfer_completed", _command(transfer_completed=True)),
    ("offline_plan", "result_verified", _command(result_verified=True)),
    ("offline_plan", "failure_reason", _command(failure_reason="CONNECTION_TIMED_OUT")),
    ("offline_plan", "timeout_stage", _command(timeout_stage="connect")),
    ("offline_plan", "returncode", _command(returncode=0)),
    ("offline_plan", "rejected", _eligibility("rejected", ["X"])),
    # failed: a reason is mandatory, the result is never verified, eligibility rejected.
    ("connection_timeout", "transfer_without_summary", _command(transfer_completed=True)),
    ("connection_timeout", "no_failure_reason", _command(failure_reason=None)),
    ("connection_timeout", "pending", _eligibility("pending", [])),
    ("no_server", "no_failure_reason", _command(failure_reason=None)),
    ("no_server", "pending", _eligibility("pending", [])),
    # interrupted: same outcome rules as failed.
    ("interrupted", "no_failure_reason", _command(failure_reason=None)),
    ("interrupted", "result_verified", _command(result_verified=True)),
    ("interrupted", "pending", _eligibility("pending", [])),
    # completed: no failure reason, eligibility not rejected.
    ("captured_success", "failure_reason", _command(failure_reason="TRAFFIC_FAILED")),
    ("captured_success", "rejected", _eligibility("rejected", ["X"])),
    ("captured_success", "timeout_stage", _command(timeout_stage="execution")),
]


@pytest.mark.parametrize(
    ("name", "label", "mutate"), INCOHERENT, ids=[f"{row[0]}-{row[1]}" for row in INCOHERENT]
)
def test_aud02_incoherent_outcomes_fail_verification(fresh, name, label, mutate) -> None:
    run = fresh(name)
    mutate(run)
    with pytest.raises(ArtifactIntegrityError):
        verify_run(run)
    assert cli_verify(run) == 3


def test_aud02_reproduced_case_reports_no_transfer(fresh) -> None:
    """The exact audit reproduction: planned set claiming transfer_completed=true."""
    run = fresh("offline_plan")
    _command(transfer_completed=True)(run)
    result = subprocess.run(
        [sys.executable, "-m", "diaglab", "verify", "--run", str(run)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 3
    assert '"transfer_completed": true' not in result.stdout


# --------------------------------------------------------------------------- AUD-03


def _config(change):
    def apply(run: Path) -> None:
        edit_json(run, "config.json", change)
        rehash(run)

    return apply


INVALID_CONFIG = [
    ("missing_target", _config(lambda c: c.pop("target"))),
    ("missing_traffic", _config(lambda c: c.pop("traffic"))),
    ("string_duration", _config(lambda c: c["traffic"].update(duration_s="30"))),
    ("unknown_field", _config(lambda c: c.update(unexpected=True))),
    ("public_target", _config(lambda c: c["target"].update(host="8.8.8.8"))),
]


@pytest.mark.parametrize(
    ("label", "mutate"), INVALID_CONFIG, ids=[row[0] for row in INVALID_CONFIG]
)
@pytest.mark.parametrize("name", ["captured_success", "offline_plan", "connection_timeout"])
def test_aud03_invalid_recorded_config_is_artifact_invalid(fresh, name, label, mutate) -> None:
    run = fresh(name)
    mutate(run)
    with pytest.raises(ArtifactIntegrityError):
        verify_run(run)
    result = subprocess.run(
        [sys.executable, "-m", "diaglab", "verify", "--run", str(run)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 3, (result.returncode, result.stderr)
    assert "CONFIG_INVALID" not in result.stderr
    assert "Traceback" not in result.stderr


def test_aud03_config_validate_still_exits_1_for_invalid_files(tmp_path, base_config) -> None:
    data = dict(base_config)
    data.pop("target")
    path = tmp_path / "invalid.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "diaglab", "config", "validate", "--config", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, (result.returncode, result.stderr)


@pytest.mark.parametrize("label", ["missing_target", "string_duration"])
def test_aud03_verify_only_ever_returns_0_2_or_3(fresh, label) -> None:
    run = fresh("captured_success")
    dict(INVALID_CONFIG)[label](run)
    assert cli_verify(run) in (0, 2, 3)
