"""LC-01–13: independent tests for the G2 receiver lifecycle (docs/RECEIVER_LIFECYCLE.md),
written from the contract before reading scripts/receiver_lifecycle.py.

Where the contract leaves a detail open, the binding test assumption is recorded as LR-n
in Claude's canonical review file and named in the test; a disputed LR goes to Denis.

LR-1  Lifecycle success means lifecycle_errors == []. Codes are UPPER_SNAKE strings. Only
      the codes the contract names (SESSION_WAIT_TIMEOUT, OUTPUT_UNAVAILABLE, ...) are
      asserted by name; other failures are asserted as "some error" plus the step's flags.
LR-2  `commands` maps or lists per-command records for the issued stop / cleanup / capture
      commands, found by name. Fields: returncode, timed_out, output_overflow. The SSH
      session is not an issued command: its timeout and overflow are asserted through
      lifecycle codes, and through a session entry only if one is present.
LR-3  lifecycle.json holds the same record that finish_session returns.
LR-4  Bundle files are private: no group/other permission bits.
LR-5  Invalid timeouts (zero, negative, NaN, infinite) raise before any command runs.
LR-6  Receiver evidence is saved as receiver-<name> with the decoded bytes; checksums.json
      names every other bundle file with its SHA-256 (format otherwise unpinned).
LR-7  A KeyboardInterrupt during shutdown may propagate after recording, but cleanup and
      capture still run and lifecycle.json records an error.
"""

from __future__ import annotations

import json
import math
import os
import re
import stat
import subprocess
import sys
import time

import pytest

from .conftest import CONTENT, REQUIRED, eventually, exists, lifecycle, running, sha256

CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
RECORD_KEYS = {
    "schema_version",
    "traffic_failure",
    "lifecycle_errors",
    "cleanup_verified",
    "evidence_verified",
    "local_session_reaped",
    "commands",
    "missing_files",
}


def step(record: dict, *words: str) -> dict:
    """LR-2: the per-step command record whose name contains any of `words`."""
    commands = record["commands"]
    entries = (
        commands.items()
        if isinstance(commands, dict)
        else [(c.get("step") or c.get("name") or "", c) for c in commands]
    )
    matches = [entry for name, entry in entries if any(w in str(name).lower() for w in words)]
    assert len(matches) >= 1, (words, list(dict(entries)))
    return matches[0]


def session_entry(record: dict) -> dict | None:
    """LR-2: the optional per-session record, if the implementation keeps one."""
    try:
        return step(record, "session", "wait")
    except AssertionError:
        return None


def assert_record_shape(record: dict) -> None:
    assert RECORD_KEYS <= set(record), set(record)
    assert record["schema_version"] == "1.0"
    assert isinstance(record["lifecycle_errors"], list)
    assert all(isinstance(c, str) and CODE.fullmatch(c) for c in record["lifecycle_errors"])
    for key in ("cleanup_verified", "evidence_verified", "local_session_reaped"):
        assert type(record[key]) is bool, key
    assert isinstance(record["missing_files"], list)


def persisted(harness) -> dict:
    return json.loads((harness.output / "lifecycle.json").read_text())


def assert_later_steps_ran(harness) -> None:
    steps = harness.steps()
    assert "cleanup" in steps and "capture" in steps, steps
    assert steps.index("cleanup") < steps.index("capture"), steps  # contract order 4 then 5


# ----------------------------------------------------------------- LC-01 normal completion


def test_lc01_normal_completion_is_a_clean_verified_record(harness) -> None:
    session = harness.start("normal")
    session_pid, grandchild = harness.pid("session.pid"), harness.pid("session.grandchild.pid")
    record = harness.finish(session)
    assert_record_shape(record)
    assert record["lifecycle_errors"] == []
    assert record["traffic_failure"] is None
    assert record["cleanup_verified"] is True
    assert record["evidence_verified"] is True
    assert record["local_session_reaped"] is True
    assert record["missing_files"] == []
    assert harness.steps() == ["stop", "stop-saw-output=True", "cleanup", "capture"]
    assert not exists(session_pid)  # reaped, not left as a zombie
    assert eventually(lambda: not running(grandchild))
    assert persisted(harness) == record  # LR-3


def test_lc01_bundle_holds_verified_evidence_and_checksums(harness) -> None:
    harness.finish(harness.start("normal"))
    out = harness.output
    for name in REQUIRED:  # LR-6
        assert (out / f"receiver-{name}").read_bytes() == CONTENT[name], name
    listed = (out / "checksums.json").read_text()
    for path in out.iterdir():
        if path.name != "checksums.json":
            assert path.name in listed, path.name
            assert sha256(path.read_bytes()) in listed, path.name
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0, path.name  # LR-4


# ------------------------------------------- LC-02 the G2 regression: shutdown wait timeout


@pytest.mark.parametrize("behavior", ["stall", "stall_ignore_term"])
def test_lc02_session_timeout_still_cleans_up_captures_and_reaps(harness, behavior) -> None:
    session = harness.start(behavior)
    session_pid, grandchild = harness.pid("session.pid"), harness.pid("session.grandchild.pid")
    failure = "EXECUTION_DEADLINE_EXCEEDED"
    started = time.monotonic()
    record = harness.finish(session, traffic_failure=failure)
    elapsed = time.monotonic() - started
    assert_record_shape(record)
    assert "SESSION_WAIT_TIMEOUT" in record["lifecycle_errors"]
    assert record["traffic_failure"] == failure  # never replaced by the lifecycle error
    assert_later_steps_ran(harness)
    assert record["cleanup_verified"] is True  # verified independently after the timeout
    assert record["evidence_verified"] is True
    assert record["local_session_reaped"] is True
    entry = session_entry(record)
    assert entry is None or entry["timed_out"] is True
    assert not exists(session_pid)
    assert eventually(lambda: not running(grandchild))  # the whole owned group
    assert elapsed < 20, elapsed  # bounded: wait 1 s + grace 0.5 s + fast commands
    assert persisted(harness) == record


def test_lc02_other_processes_running_the_same_program_are_untouched(harness) -> None:
    """Never kill by executable name or arbitrary PID: an unrelated process running the
    identical session program, in its own session, survives a forced shutdown."""
    decoy_work = harness.work.parent / "decoy"
    decoy_work.mkdir()
    decoy = subprocess.Popen(
        [sys.executable, str(harness.fake), "session", "stall_ignore_term", str(decoy_work)],
        start_new_session=True,
    )
    try:
        harness.finish(harness.start("stall_ignore_term"))
        assert decoy.poll() is None and running(decoy.pid)
    finally:
        decoy.kill()
        decoy.wait(timeout=5)


# ------------------------------------------------------------- LC-03 traffic failure field


@pytest.mark.parametrize("failure", [None, "EXECUTION_DEADLINE_EXCEEDED", "x: ünïcode / 'q' \"\n"])
def test_lc03_traffic_failure_is_preserved_verbatim(harness, failure) -> None:
    record = harness.finish(harness.start("stall"), traffic_failure=failure)
    assert record["traffic_failure"] == failure
    assert persisted(harness)["traffic_failure"] == failure
    assert failure not in record["lifecycle_errors"]


# ---------------------------------------------------------------- LC-04 stop command faults


def test_lc04_nonzero_stop_is_recorded_and_later_steps_run(harness) -> None:
    record = harness.finish(harness.start("normal"), stop="fail")
    assert record["lifecycle_errors"]
    assert step(record, "stop")["returncode"] == 3
    assert_later_steps_ran(harness)
    assert record["cleanup_verified"] is True


def test_lc04_hanging_stop_times_out_its_own_group(harness) -> None:
    session = harness.start("stall")
    started = time.monotonic()
    record = harness.finish(session, stop="hang", command_timeout=1.0)
    # bound: stop 1 s + session wait 1 s + grace, plus fast cleanup/capture
    assert time.monotonic() - started < 8, "command_timeout must actually bound the stop"
    assert record["lifecycle_errors"]
    assert step(record, "stop")["timed_out"] is True
    assert_later_steps_ran(harness)
    stop_child = harness.pid("stop.grandchild.pid")
    assert eventually(lambda: not running(stop_child))  # the command's owned group too


def test_lc04_stop_output_overflow_is_bounded_and_recorded(harness) -> None:
    started = time.monotonic()
    record = harness.finish(harness.start("normal"), stop="flood")
    assert time.monotonic() - started < 20  # drained; the child never blocks on a full pipe
    assert record["lifecycle_errors"]
    assert step(record, "stop")["output_overflow"] is True
    assert_later_steps_ran(harness)


# ------------------------------------------------------------- LC-05 cleanup verification

BAD_CLEANUP = ["partial", "extra", "missing_key", "string_true", "invalid", "nonzero_ok"]


@pytest.mark.parametrize("behavior", BAD_CLEANUP)
def test_lc05_cleanup_needs_exactly_three_true_booleans(harness, behavior) -> None:
    record = harness.finish(harness.start("normal"), cleanup=behavior)
    assert record["cleanup_verified"] is False
    assert record["lifecycle_errors"]
    assert "capture" in harness.steps()  # capture is attempted even when cleanup fails
    assert record["evidence_verified"] is True
    assert persisted(harness)["cleanup_verified"] is False


def test_lc05_hanging_cleanup_times_out_and_capture_still_runs(harness) -> None:
    session = harness.start("normal")
    started = time.monotonic()
    record = harness.finish(session, cleanup="hang", command_timeout=1.0)
    assert time.monotonic() - started < 8, "command_timeout must actually bound the cleanup"
    assert record["cleanup_verified"] is False
    assert step(record, "cleanup")["timed_out"] is True
    assert "capture" in harness.steps()
    assert eventually(lambda: not running(harness.pid("cleanup.grandchild.pid")))


# ------------------------------------------------------------ LC-06 evidence verification


def test_lc06_listed_missing_file_is_explicit(harness) -> None:
    record = harness.finish(harness.start("normal"), capture="missing_listed")
    assert record["evidence_verified"] is False
    assert record["missing_files"] == ["server.stderr"]
    assert record["lifecycle_errors"]
    assert not (harness.output / "receiver-server.stderr").exists()  # no invented substitute


def test_lc06_contradictory_missing_inventory_is_never_verified(harness) -> None:
    """All four files arrive, yet the receiver also reports one as missing: an
    inconsistent capture must not be marked verified."""
    record = harness.finish(harness.start("normal"), capture="missing_contradiction")
    assert record["evidence_verified"] is False
    assert record["lifecycle_errors"]


def test_lc06_silently_absent_file_is_still_missing(harness) -> None:
    record = harness.finish(harness.start("normal"), capture="missing_silent")
    assert record["evidence_verified"] is False
    assert "server.stderr" in record["missing_files"]
    assert not (harness.output / "receiver-server.stderr").exists()


@pytest.mark.parametrize(
    "behavior",
    ["bad_base64", "bad_digest", "bad_size", "unknown_name", "traversal", "invalid", "nonzero"],
)
def test_lc06_corrupt_or_failed_capture_is_never_verified(harness, behavior) -> None:
    record = harness.finish(harness.start("normal"), capture=behavior)
    assert_record_shape(record)
    assert record["evidence_verified"] is False
    assert record["lifecycle_errors"]
    assert record["cleanup_verified"] is True  # unrelated steps keep their own outcome
    assert persisted(harness)["evidence_verified"] is False
    root = harness.work.parent
    assert not (harness.output.parent / "escape.txt").exists()
    assert not (root / "escape.txt").exists()
    assert not any(p.name.endswith("escape.txt") for p in harness.output.iterdir())


def test_lc06_capture_overflow_is_recorded(harness) -> None:
    record = harness.finish(harness.start("normal"), capture="flood")
    assert record["evidence_verified"] is False
    assert step(record, "capture")["output_overflow"] is True


# ------------------------------------------------------------------- LC-07 output safety


def test_lc07_output_is_reserved_before_any_shutdown_command(harness) -> None:
    harness.finish(harness.start("normal"))
    assert "stop-saw-output=True" in harness.steps()


def test_lc07_nonempty_output_is_never_overwritten_and_steps_still_run(harness) -> None:
    harness.output.mkdir(parents=True)
    keep = harness.output / "lifecycle.json"
    keep.write_text("owner data")
    record = harness.finish(harness.start("stall"), traffic_failure="T")
    assert "OUTPUT_UNAVAILABLE" in record["lifecycle_errors"]
    assert keep.read_text() == "owner data"
    assert sorted(os.listdir(harness.output)) == ["lifecycle.json"]
    assert_later_steps_ran(harness)
    assert record["cleanup_verified"] is True and record["traffic_failure"] == "T"
    assert record["local_session_reaped"] is True


def test_lc07_unwritable_destination_returns_the_record(harness) -> None:
    harness.output.parent.mkdir(parents=True)
    harness.output.parent.joinpath("blocker").write_text("a file, not a directory")
    record = harness.finish(harness.start("normal"), output=harness.output.parent / "blocker" / "x")
    assert "OUTPUT_UNAVAILABLE" in record["lifecycle_errors"]
    assert_later_steps_ran(harness)
    assert record["cleanup_verified"] is True


# --------------------------------------------------------------- LC-08 session output


def test_lc08_session_output_flood_cannot_deadlock_the_session(harness) -> None:
    session = harness.start("flood")
    started = time.monotonic()
    record = harness.finish(session, shutdown_timeout=10.0)
    assert time.monotonic() - started < 15
    assert "SESSION_WAIT_TIMEOUT" not in record["lifecycle_errors"]  # it exited after stop
    entry = session_entry(record)
    assert entry is None or entry["output_overflow"] is True
    assert record["lifecycle_errors"]  # overflow is a lifecycle error (code unpinned)
    assert record["local_session_reaped"] is True


def test_lc08_a_process_outside_the_group_is_not_killed_and_cannot_hang_shutdown(
    harness,
) -> None:
    """A process that left the owned group (setsid) but still holds the session's stdout:
    it is not owned, so it must survive, and finish_session must still return within its
    bounds instead of blocking on the open pipe. Whether this counts as "reaped" is not
    pinned by the contract; reporting it as a lifecycle error is acceptable."""
    session = harness.start("escape")
    harness.wait_for_file("escapee.pid")
    escapee = harness.pid("escapee.pid")
    started = time.monotonic()
    record = harness.finish(session)
    assert time.monotonic() - started < 20
    assert running(escapee)  # never signal a process outside the owned group
    assert_later_steps_ran(harness)
    assert persisted(harness) == record


# ---------------------------------------------------------------- LC-09 argument validation


@pytest.mark.parametrize("name", ["shutdown_timeout", "command_timeout", "terminate_grace"])
@pytest.mark.parametrize("value", [0, -1, math.nan, math.inf])
def test_lc09_invalid_timeouts_are_refused_before_any_command(harness, name, value) -> None:
    session = harness.start("normal")
    try:
        with pytest.raises((ValueError, TypeError)):
            harness.finish(session, **{name: value})
        assert harness.steps() == []
    finally:
        harness.finish(session)  # then shut it down properly


def test_lc09_start_session_takes_an_argument_vector_without_a_shell(harness) -> None:
    marker = harness.work / "injected"
    with pytest.raises((TypeError, ValueError)):
        lifecycle().start_session(f"{sys.executable} -c 'print(1)'")
    session = lifecycle().start_session(
        [sys.executable, "-c", "import sys; sys.exit(0)", f"$(touch {marker})", "; touch x"]
    )
    record = harness.finish(session)
    assert not marker.exists() and not (harness.work / "x").exists()
    assert record["local_session_reaped"] is True


# --------------------------------------------------------- LC-10 operator interrupt (LR-7)


def test_lc10_keyboard_interrupt_during_shutdown_is_recorded_and_cleanup_continues(
    harness,
) -> None:
    session = harness.start("normal")
    record = None
    try:
        record = harness.finish(session, stop="sigint_parent")
    except KeyboardInterrupt:
        pass
    assert_later_steps_ran(harness)
    saved = persisted(harness)
    assert saved["lifecycle_errors"]
    if record is not None:
        assert record == saved
    assert saved["local_session_reaped"] is True
