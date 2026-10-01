"""Independent tests for TC-I-02 against docs/PHASE2_CONTRACTS.md.

TC-I-02: diaglab.traffic.runner.Iperf3TrafficAdapter -- process-group ownership,
the connect/execution deadline distinction, SIGTERM->SIGKILL escalation, bounded
output capture, and idempotent repeated stop()/wait().

Mock "iperf3" binaries are small real executables (not mocked subprocess calls),
so the actual process-group, signal, and pipe-draining behavior under test is real,
not simulated. `resolve_source`/`probe_server` are monkeypatched because they touch
live host network state (`ip -j ...`, a TCP connect) that this suite must not perform;
everything downstream of that boundary runs for real.
"""

import copy
import json
import os
import signal
import stat
import time
from pathlib import Path
from typing import Any

import pytest

import diaglab.run as run_module
from diaglab.artifacts.store import ArtifactStore
from diaglab.config import ExperimentConfig
from diaglab.exceptions import ArtifactIntegrityError, SafetyPreflightError
from diaglab.models import RunContext
from diaglab.run import RunInterrupted, _signals, run_experiment
from diaglab.traffic import runner as runner_module
from diaglab.traffic.runner import Iperf3TrafficAdapter

MOCK_SHEBANG = "#!/usr/bin/env python3\n"

SUCCESS_DOCUMENT: dict[str, Any] = {
    "start": {
        "connected": [
            {
                "socket": 5,
                "local_host": "192.0.2.10",
                "local_port": 40005,
                "remote_host": "192.0.2.20",
                "remote_port": 5201,
            }
        ],
        "version": "iperf 3.16",
        "system_info": "mock",
        "test_start": {
            "protocol": "TCP",
            "num_streams": 1,
            "omit": 0,
            "duration": 1,
            "reverse": 0,
            "bidir": 0,
        },
    },
    "intervals": [
        {
            "streams": [
                {
                    "socket": 5,
                    "start": 0.0,
                    "end": 1.0,
                    "seconds": 1.0,
                    "bytes": 1_000_000,
                    "bits_per_second": 8_000_000.0,
                    "retransmits": 0,
                    "omitted": False,
                }
            ],
            "sum": {"start": 0.0, "end": 1.0, "bytes": 1_000_000, "omitted": False},
        }
    ],
    "end": {
        "streams": [
            {
                "sender": {
                    "socket": 5,
                    "start": 0.0,
                    "end": 1.0,
                    "seconds": 1.0,
                    "bytes": 1_000_000,
                    "bits_per_second": 8_000_000.0,
                    "retransmits": 0,
                },
                "receiver": {
                    "socket": 5,
                    "start": 0.0,
                    "end": 1.0,
                    "seconds": 1.0,
                    "bytes": 1_000_000,
                    "bits_per_second": 8_000_000.0,
                },
            }
        ],
        "sum_sent": {
            "start": 0.0,
            "end": 1.0,
            "seconds": 1.0,
            "bytes": 1_000_000,
            "bits_per_second": 8_000_000.0,
            "retransmits": 0,
        },
        "sum_received": {
            "start": 0.0,
            "end": 1.0,
            "seconds": 1.0,
            "bytes": 1_000_000,
            "bits_per_second": 8_000_000.0,
        },
    },
}

CONNECTION_TIMEOUT_DOCUMENT = {
    "start": {"connected": [], "version": "iperf 3.16", "system_info": "mock"},
    "intervals": [],
    "end": {},
    "error": "unable to connect to server - Connection timed out",
}

# {behavior} is substituted with one of the branches below; MOCK_SIGNAL_FILE, when
# set, is touched right before the script exits so a test can confirm it actually ran.
MOCK_TEMPLATE = (
    MOCK_SHEBANG
    + """
import json
import os
import signal
import sys
import time

behavior = os.environ["MOCK_BEHAVIOR"]
signal_file = os.environ.get("MOCK_SIGNAL_FILE")

if behavior == "success":
    sys.stdout.write(json.dumps({success_document}))
    sys.stdout.flush()
    sys.exit(0)
elif behavior == "connection_timeout":
    sys.stdout.write(json.dumps({timeout_document}))
    sys.stdout.flush()
    sys.exit(1)
elif behavior == "hang":
    time.sleep(30)
    sys.exit(0)
elif behavior == "ignore_sigterm":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if signal_file:
        with open(signal_file, "w") as handle:
            handle.write("started")
    time.sleep(30)
    sys.exit(0)
elif behavior == "large_output":
    sys.stdout.buffer.write(b"x" * (17 * 1024 * 1024))
    sys.stdout.flush()
    sys.exit(0)
elif behavior == "nonzero_exit_no_json":
    sys.stderr.write("mock failure without JSON output")
    sys.exit(2)
else:
    raise SystemExit(f"unknown MOCK_BEHAVIOR: {{behavior}}")
"""
)


def _write_mock(tmp_path: Path) -> Path:
    script = tmp_path / "mock_iperf3.py"
    rendered = MOCK_TEMPLATE.format(
        success_document=repr(SUCCESS_DOCUMENT),
        timeout_document=repr(CONNECTION_TIMEOUT_DOCUMENT),
    )
    script.write_text(rendered, encoding="utf-8")
    mode = os.stat(script).st_mode
    os.chmod(script, mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


@pytest.fixture
def mock_executable(tmp_path: Path) -> Path:
    return _write_mock(tmp_path)


@pytest.fixture(autouse=True)
def _no_live_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test in this module runs with host network preflight disabled."""
    monkeypatch.setattr(runner_module, "resolve_source", lambda context: "192.0.2.10")
    monkeypatch.setattr(runner_module, "probe_server", lambda context, source: None)


def _approved_config_dict(
    valid_config_dict: dict[str, Any], **traffic_overrides: Any
) -> dict[str, Any]:
    data = copy.deepcopy(valid_config_dict)
    data["safety"]["dry_run"] = False
    data["safety"]["approved_profile_id"] = "test-profile-001"
    data["traffic"].update(traffic_overrides)
    return data


def _context(
    tmp_path: Path, config_dict: dict[str, Any], run_id: str = "r-" + "0" * 32
) -> RunContext:
    config = ExperimentConfig.from_dict(config_dict)
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    return RunContext(run_id, config, run_dir)


def _set_env(
    monkeypatch: pytest.MonkeyPatch, behavior: str, signal_file: Path | None = None
) -> None:
    monkeypatch.setenv("MOCK_BEHAVIOR", behavior)
    if signal_file is not None:
        monkeypatch.setenv("MOCK_SIGNAL_FILE", str(signal_file))
    else:
        monkeypatch.delenv("MOCK_SIGNAL_FILE", raising=False)


# ==============================================================================
# Successful lifecycle and process-group ownership
# ==============================================================================


def test_tc_i_02_successful_run_is_owned_in_its_own_process_group(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "success")
    context = _context(tmp_path, _approved_config_dict(valid_config_dict))
    adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    adapter.prepare(context)
    handle = adapter.start(context)
    assert handle.pid == handle.process_group_id  # start_new_session makes it the leader
    result = adapter.wait(handle)
    assert result.returncode == 0
    assert result.cleanup_verified is True
    assert result.failure_reason is None
    assert result.timed_out is False
    raw = (context.artifact_root / "client.json").read_text()
    assert json.loads(raw) == SUCCESS_DOCUMENT


def test_tc_i_02_prepare_refuses_non_baseline_pilot_scope(
    tmp_path: Path, valid_config_dict: dict[str, Any], mock_executable: Path
) -> None:
    data = _approved_config_dict(valid_config_dict)
    data["evidence_kind"] = "measured"
    context = _context(tmp_path, data)
    adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    with pytest.raises(SafetyPreflightError):
        adapter.prepare(context)


def test_tc_i_02_prepare_refuses_when_raw_artifacts_already_exist(
    tmp_path: Path, valid_config_dict: dict[str, Any], mock_executable: Path
) -> None:
    context = _context(tmp_path, _approved_config_dict(valid_config_dict))
    with ArtifactStore(context.artifact_root) as store:
        store.write("client.json", b"{}")
    adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    with pytest.raises(SafetyPreflightError):
        adapter.prepare(context)


# ==============================================================================
# Connect-stage vs. execution-deadline timeout distinction
# ==============================================================================


def test_tc_i_02_parsed_connection_failure_reports_connect_stage(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "connection_timeout")
    context = _context(tmp_path, _approved_config_dict(valid_config_dict))
    adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    adapter.prepare(context)
    handle = adapter.start(context)
    result = adapter.wait(handle)
    assert result.returncode != 0
    assert result.failure_reason == "CONNECTION_TIMED_OUT"
    assert result.timeout_stage == "connect"
    assert result.timed_out is False  # classified from content, not from the watchdog
    assert result.cleanup_verified is True


def test_tc_i_02_hung_process_is_killed_at_the_execution_deadline(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "hang")
    data = _approved_config_dict(
        valid_config_dict,
        connect_timeout_s=0.2,
        omit_s=0,
        duration_s=0.3,
        finish_timeout_s=0.2,
        terminate_grace_s=0.3,
    )
    context = _context(tmp_path, data)
    adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    adapter.prepare(context)
    handle = adapter.start(context)
    started = time.monotonic()
    result = adapter.wait(handle)
    elapsed = time.monotonic() - started
    assert result.timed_out is True
    assert result.timeout_stage == "execution"
    assert result.failure_reason == "EXECUTION_DEADLINE_EXCEEDED"
    assert result.cleanup_verified is True
    # Generously bounded: deadline (~0.7s) + grace (0.3s) + a little slack, never 30s.
    assert elapsed < 5.0


# ==============================================================================
# SIGTERM -> SIGKILL escalation
# ==============================================================================


def test_tc_i_02_sigterm_ignoring_process_is_escalated_to_sigkill(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal_file = tmp_path / "started.marker"
    _set_env(monkeypatch, "ignore_sigterm", signal_file=signal_file)
    data = _approved_config_dict(
        valid_config_dict,
        connect_timeout_s=0.2,
        omit_s=0,
        duration_s=0.2,
        finish_timeout_s=0.2,
        terminate_grace_s=0.3,
    )
    context = _context(tmp_path, data)
    adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    adapter.prepare(context)
    handle = adapter.start(context)
    deadline = time.monotonic() + 2.0
    while not signal_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert signal_file.exists(), "mock process never confirmed its SIGTERM handler was armed"
    started = time.monotonic()
    result = adapter.wait(handle)
    elapsed = time.monotonic() - started
    assert result.cleanup_verified is True
    assert result.timed_out is True
    # Must actually have been killed, not left running past the grace window.
    with pytest.raises(ProcessLookupError):
        os.kill(handle.pid, 0)
    assert elapsed < 5.0


# ==============================================================================
# Bounded output capture
# ==============================================================================


def test_tc_i_02_oversized_stdout_ends_the_run_and_preserves_the_captured_prefix(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "large_output")
    context = _context(tmp_path, _approved_config_dict(valid_config_dict))
    adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    adapter.prepare(context)
    handle = adapter.start(context)
    result = adapter.wait(handle)
    assert result.failure_reason == "OUTPUT_LIMIT_EXCEEDED"
    assert result.cleanup_verified is True
    captured = (context.artifact_root / "client.json").stat().st_size
    assert 0 < captured <= 16 * 1024 * 1024


# ==============================================================================
# Nonzero exit without a parseable error document
# ==============================================================================


def test_tc_i_02_nonzero_exit_without_json_error_is_a_generic_process_failure(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "nonzero_exit_no_json")
    context = _context(tmp_path, _approved_config_dict(valid_config_dict))
    adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    adapter.prepare(context)
    handle = adapter.start(context)
    result = adapter.wait(handle)
    assert result.returncode == 2
    assert result.failure_reason == "PROCESS_NONZERO_EXIT"
    assert result.cleanup_verified is True


# ==============================================================================
# Repeated stop()/wait() idempotency and unknown-handle refusal
# ==============================================================================


def test_tc_i_02_repeated_wait_returns_the_same_result_without_restarting_cleanup(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "success")
    context = _context(tmp_path, _approved_config_dict(valid_config_dict))
    adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    adapter.prepare(context)
    handle = adapter.start(context)
    first = adapter.wait(handle)
    second = adapter.wait(handle)
    assert first == second


def test_tc_i_02_repeated_stop_after_success_is_a_safe_no_op(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "success")
    context = _context(tmp_path, _approved_config_dict(valid_config_dict))
    adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    adapter.prepare(context)
    handle = adapter.start(context)
    adapter.wait(handle)
    adapter.stop(handle)  # already cleaned; must not raise or re-signal anything
    adapter.stop(handle)


def test_tc_i_02_unknown_handle_is_refused_without_signalling_any_process(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "success")
    context = _context(tmp_path, _approved_config_dict(valid_config_dict))
    adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    adapter.prepare(context)
    handle = adapter.start(context)
    adapter.wait(handle)
    other_context = _context(
        tmp_path, _approved_config_dict(valid_config_dict), run_id="r-" + "1" * 32
    )
    other_adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    other_adapter.prepare(other_context)
    foreign_handle = other_adapter.start(other_context)
    try:
        with pytest.raises(SafetyPreflightError):
            adapter.stop(foreign_handle)
    finally:
        other_adapter.wait(foreign_handle)


def test_tc_i_02_adapter_cannot_be_reused_for_a_second_run(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "success")
    context = _context(tmp_path, _approved_config_dict(valid_config_dict))
    adapter = Iperf3TrafficAdapter(executable=str(mock_executable))
    adapter.prepare(context)
    adapter.start(context)
    with pytest.raises(SafetyPreflightError):
        adapter.prepare(context)


# ==============================================================================
# run_experiment: offline planning never touches the network, and SIGINT/SIGTERM
# during a live run still verify cleanup. These exercise diaglab.run, not the
# adapter directly, since that is where _signals()/offline mode actually live.
# ==============================================================================


def test_tc_i_02_offline_plan_performs_no_subprocess_or_socket_activity(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("offline planning must not resolve a route or probe a server")

    monkeypatch.setattr(runner_module, "resolve_source", _forbidden)
    monkeypatch.setattr(runner_module, "probe_server", _forbidden)
    config = ExperimentConfig.from_dict(copy.deepcopy(valid_config_dict))
    manifest_path = run_experiment(config, tmp_path / "plan", execute=False, run_role="pilot")
    manifest = json.loads(manifest_path.read_text())
    assert manifest["state"] == "planned"
    command = json.loads((tmp_path / "plan" / "command.json").read_text())
    assert command["execute"] is False
    assert command["transfer_completed"] is False
    assert "<LIVE_SOURCE_IP>" in command["argv"]


def test_tc_i_02_sigint_during_a_live_run_verifies_cleanup_and_marks_interrupted(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "hang")
    monkeypatch.setattr(runner_module, "resolve_source", lambda context: "192.0.2.10")
    monkeypatch.setattr(runner_module, "probe_server", lambda context, source: None)
    data = _approved_config_dict(
        valid_config_dict,
        connect_timeout_s=0.1,
        omit_s=0,
        duration_s=20,
        finish_timeout_s=0.2,
        terminate_grace_s=0.2,
    )
    config = ExperimentConfig.from_dict(data)

    original_start = Iperf3TrafficAdapter.start

    def _start_then_self_interrupt(self: Iperf3TrafficAdapter, context: RunContext):
        handle = original_start(self, context)
        os.kill(os.getpid(), signal.SIGINT)
        return handle

    monkeypatch.setattr(Iperf3TrafficAdapter, "start", _start_then_self_interrupt)

    with pytest.raises(RunInterrupted):
        run_experiment(
            config,
            tmp_path / "live",
            execute=True,
            run_role="pilot",
            executable=str(mock_executable),
        )

    manifest = json.loads((tmp_path / "live" / "manifest.json").read_text())
    assert manifest["state"] == "interrupted"
    assert manifest["cleanup"]["status"] == "verified"
    assert manifest["eligibility"]["status"] == "rejected"


def test_signals_context_suppresses_a_second_signal_during_handling() -> None:
    """Unit-level check of the suppress-duplicate-signal behavior _signals() relies on."""
    received: list[int] = []
    with pytest.raises(RunInterrupted):
        with _signals():
            os.kill(os.getpid(), signal.SIGINT)
            # If the handler re-armed itself, this second signal would raise again
            # here instead of being suppressed until the first exception propagates.
            os.kill(os.getpid(), signal.SIGINT)
            received.append(1)
    assert received == []


# ==============================================================================
# Regression test for a defect reported in Claude's Phase 2 code review: a failure
# during run_experiment's artifact-finalization tail used to silently discard an
# already-caught execution failure instead of chaining to it, because the
# preceding `except` block had already cleared sys.exc_info() by the time
# finalization ran. Codex fixed this by explicitly chaining a finalization-time
# exception to any pre-existing `failure` (see run.py). No xfail marker: the fix
# is verified below and this is now a plain regression test guarding against it
# reappearing.
# ==============================================================================


def test_tc_i_02_finalization_failure_preserves_the_original_execution_failure(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    mock_executable: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_env(monkeypatch, "connection_timeout")
    data = _approved_config_dict(valid_config_dict)
    config = ExperimentConfig.from_dict(data)

    real_validate_record = run_module.validate_record

    def _fail_on_checksums(name: str, record: Any) -> None:
        if name == "checksums":
            raise ArtifactIntegrityError("simulated finalization failure")
        real_validate_record(name, record)

    monkeypatch.setattr(run_module, "validate_record", _fail_on_checksums)

    with pytest.raises(Exception) as excinfo:  # noqa: PT011 - exact type is the point under test
        run_experiment(
            config,
            tmp_path / "run",
            execute=True,
            run_role="pilot",
            executable=str(mock_executable),
        )

    # The real cause (the connection timeout that actually failed the run) must
    # still be discoverable from the raised exception, via __cause__/__context__,
    # even though a second, unrelated failure also happened during finalization.
    chain = []
    current = excinfo.value
    while current is not None:
        chain.append(current)
        current = current.__cause__ or current.__context__
    reason_codes = [getattr(exc, "reason_code", None) for exc in chain]
    assert "CONNECTION_TIMED_OUT" in reason_codes, (
        f"original execution failure was lost; exception chain was: {chain!r}"
    )
