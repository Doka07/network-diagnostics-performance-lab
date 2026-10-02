"""TG-02, TG-03, TG-04 (core), TG-06, TG-07 and R-12..R-17 for diaglab.inspection.

Written from docs/GUI_CONTRACTS.md and Claude's resolutions R-1..R-22 (private canonical
review, 2026-10-01) before any implementation existed. CLI exit codes in PARITY were
pinned from the pre-refactor `diaglab verify` on 2026-10-01; they are the oracle, not
whatever the refactored CLI happens to return.
"""

from __future__ import annotations

import builtins
import dataclasses
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

import pytest

from diaglab.run import verify_run

from .conftest import core
from .runs import PAYLOADS, cli_verify, edit_json, rehash, tree_state

# ---------------------------------------------------------------------------- helpers


def codes(inspection) -> set[str]:
    return {str(issue.code) for issue in inspection.issues}


@contextmanager
def deadline(seconds: int):
    """Fail instead of hanging forever (hostile inputs must stay bounded)."""

    def expire(signum, frame):
        raise AssertionError(f"inspection did not finish within {seconds}s")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


# ---------------------------------------------------------------- TG-03 CLI parity (R-1)


def _drop(name: str):
    return lambda run: (run / name).unlink()


def _append(name: str, data: bytes):
    def apply(run: Path) -> None:
        with (run / name).open("ab") as handle:
            handle.write(data)

    return apply


def _symlink_payload(run: Path) -> None:
    os.replace(run / "client.stderr", run / "moved.stderr")
    (run / "moved.stderr").rename(run.parent / f"{run.name}.outside")
    os.symlink(run.parent / f"{run.name}.outside", run / "client.stderr")


def _state_running(run: Path) -> None:
    edit_json(run, "manifest.json", lambda m: m.update(state="running"))


def _summary_value(run: Path) -> None:
    edit_json(
        run,
        "traffic_summary.json",
        lambda s: s["report"]["receiver"].update(
            bytes_count=s["report"]["receiver"]["bytes_count"] + 1
        ),
    )
    rehash(run)


def _event_dropped(run: Path) -> None:
    lines = (run / "events.jsonl").read_bytes().splitlines(keepends=True)
    (run / "events.jsonl").write_bytes(b"".join(lines[:-1]))
    rehash(run)


def _config_identity(run: Path) -> None:
    edit_json(run, "config.json", lambda c: c.update(campaign_id="c-tampered-001"))
    rehash(run)


def _aud02_planned_claims_transfer(run: Path) -> None:
    edit_json(run, "command.json", lambda c: c.update(transfer_completed=True))
    rehash(run)


def _aud03_config_missing_target(run: Path) -> None:
    edit_json(run, "config.json", lambda c: c.pop("target"))
    rehash(run)


# (run, mutation, integrity, expected code or None, CLI exit pinned 2026-10-01)
PARITY = [
    ("captured_success", None, "verified", None, 0),
    ("connection_timeout", None, "verified", None, 0),
    ("four_omit", None, "verified", None, 0),
    ("four_derived", None, "verified", None, 0),
    ("no_server", None, "verified", None, 0),
    ("gap", None, "verified", None, 0),
    ("interrupted", None, "verified", None, 0),
    ("offline_plan", None, "verified", None, 0),
    ("phase1_manifest", None, "verified", None, 0),
    ("captured_success", _drop("client.json"), "failed", "INPUT_MISSING", 2),
    ("captured_success", _drop("checksums.json"), "failed", "INPUT_MISSING", 2),
    ("captured_success", _drop("manifest.json"), "failed", "INPUT_MISSING", 2),
    ("captured_success", _append("client.stderr", b"x"), "failed", "CHECKSUM_MISMATCH", 3),
    ("captured_success", _append("events.jsonl", b"\xff"), "failed", "CHECKSUM_MISMATCH", 3),
    (
        "captured_success",
        lambda run: (run / "extra.txt").write_text("x"),
        "failed",
        "ARTIFACT_COVERAGE_MISMATCH",
        3,
    ),
    (
        "captured_success",
        lambda run: (run / "subdir").mkdir(),
        "failed",
        "ARTIFACT_COVERAGE_MISMATCH",
        3,
    ),
    (
        "captured_success",
        lambda run: (run / ".run.lock").touch(),
        "unfinalized",
        "RUN_UNFINALIZED",
        3,
    ),
    (
        "captured_success",
        lambda run: (run / ".creation.lock").touch(),
        "unfinalized",
        "RUN_UNFINALIZED",
        3,
    ),
    ("captured_success", _state_running, "unfinalized", "RUN_UNFINALIZED", 3),
    ("captured_success", _symlink_payload, "failed", "PATH_UNSAFE", 3),
    ("captured_success", _summary_value, "failed", "RESULT_MISMATCH", 3),
    ("captured_success", _event_dropped, "failed", "EVENT_HISTORY_MISMATCH", 3),
    ("captured_success", _config_identity, "failed", "CONFIG_IDENTITY_MISMATCH", 3),
    # Audit regressions (R-26): the shared verification routine must include AUD-02/03.
    ("offline_plan", _aud02_planned_claims_transfer, "failed", "RESULT_MISMATCH", 3),
    ("captured_success", _aud03_config_missing_target, "failed", "SCHEMA_INVALID", 3),
]


@pytest.mark.parametrize(
    ("name", "mutate", "integrity", "code", "exit_code"),
    PARITY,
    ids=[
        f"{row[0]}-{getattr(row[1], '__name__', 'intact') if row[1] else 'intact'}-{row[3]}"
        for row in PARITY
    ],
)
def test_tg03_inspection_matches_pinned_cli_verify(
    fresh, name, mutate, integrity, code, exit_code
) -> None:
    run = fresh(name)
    if mutate is not None:
        mutate(run)
    before = tree_state(run) if run.exists() else None
    inspection = core().load_run(run)

    assert str(inspection.integrity) == integrity
    # R-2: issues non-empty iff not verified; verification present iff verified.
    assert bool(inspection.issues) == (integrity != "verified")
    assert (inspection.verification is not None) == (integrity == "verified")
    if code is not None:
        assert code in codes(inspection), codes(inspection)
    assert cli_verify(run) == exit_code
    if integrity == "verified":
        assert inspection.verification == verify_run(run)
    if before is not None:
        assert tree_state(run) == before  # GC-4 for every matrix row


def test_tg03_missing_root_is_input_missing_with_exit_2(tmp_path: Path) -> None:
    inspection = core().load_run(tmp_path / "absent")
    assert str(inspection.integrity) == "failed"
    assert "INPUT_MISSING" in codes(inspection)
    assert cli_verify(tmp_path / "absent") == 2


@pytest.mark.parametrize(
    ("name", "state", "completed", "verified", "reasons"),
    [
        ("captured_success", "completed", True, True, ()),
        ("connection_timeout", "failed", False, False, ()),
        ("no_server", "failed", True, False, ()),
        ("gap", "failed", True, False, ()),
        ("interrupted", "interrupted", False, False, ()),
        ("offline_plan", "planned", False, False, ()),
        ("phase1_manifest", "planned", False, False, ("PLANNED_ONLY",)),
    ],
)
def test_tg03_verified_outcomes_are_pinned(
    fresh, name, state, completed, verified, reasons
) -> None:
    inspection = core().load_run(fresh(name))
    result = inspection.verification
    assert result.verified is True
    assert result.state == state == inspection.state
    assert result.transfer_completed is completed
    assert result.result_verified is verified
    assert tuple(result.reasons) == reasons
    assert inspection.eligibility in ("pending", "rejected")


# ---------------------------------------------------------- TG-02 snapshot consistency


def test_tg02_snapshot_bytes_and_hashes_equal_the_files_read(fresh) -> None:
    run = fresh("captured_success")
    inspection = core().load_run(run)
    snapshot = inspection.snapshot
    assert snapshot.finalized is True
    assert set(snapshot.entry_names) == set(os.listdir(run))
    by_name = {artifact.name: artifact for artifact in snapshot.artifacts}
    assert set(by_name) == {name for name in PAYLOADS if (run / name).exists()}
    for name, artifact in by_name.items():
        data = (run / name).read_bytes()
        assert artifact.data == data
        assert isinstance(artifact.data, bytes)
        assert artifact.sha256 == hashlib.sha256(data).hexdigest()
        assert artifact.size_bytes == len(data)
        assert artifact.issue is None


@pytest.mark.parametrize("change", ["replace_same_content", "append_byte"])
def test_tg02_files_changed_during_capture_yield_snapshot_changed(fresh, change) -> None:
    run = fresh("captured_success")
    fired = []

    def progress(completed: int, total: int) -> None:
        if completed >= 1 and not fired:
            fired.append(True)
            for name in PAYLOADS:
                path = run / name
                if not path.exists():
                    continue
                if change == "replace_same_content":
                    # Same bytes, new inode: only identity checks can catch this.
                    staging = run.parent / f"{name}.staging"
                    staging.write_bytes(path.read_bytes())
                    os.replace(staging, path)
                else:
                    with path.open("ab") as handle:
                        handle.write(b" ")

    inspection = core().load_run(run, progress=progress)
    assert fired, "progress callback never reported a completed artifact"
    assert str(inspection.integrity) == "failed"
    assert "SNAPSHOT_CHANGED" in codes(inspection)
    assert inspection.report is None
    assert inspection.verification is None


def test_tg02_display_uses_cached_snapshot_not_current_files(fresh) -> None:
    from .conftest import view

    run = fresh("captured_success")
    inspection = core().load_run(run)
    expected = view().build_view(inspection)
    for name in PAYLOADS:
        if (run / name).exists():
            (run / name).write_bytes(b"{}")
    # Building the view again must not re-read the (now different) files.
    assert view().build_view(inspection) == expected


def test_tg02_snapshot_records_are_immutable(fresh) -> None:
    inspection = core().load_run(fresh("captured_success"))
    with pytest.raises(dataclasses.FrozenInstanceError):
        inspection.integrity = "failed"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        inspection.snapshot.artifacts[0].data = b""  # type: ignore[misc]
    with pytest.raises(TypeError):
        inspection.manifest["state"] = "completed"  # type: ignore[index]
    assert isinstance(inspection.snapshot.artifacts, tuple)
    assert isinstance(inspection.issues, tuple)


def test_tg02_capture_inspect_composition_equals_load_run(fresh) -> None:
    run = fresh("four_omit")
    module = core()
    composed = module.inspect_snapshot(module.capture_run(run))
    direct = module.load_run(run)
    assert composed.integrity == direct.integrity
    assert composed.verification == direct.verification
    assert composed.report == direct.report


# ------------------------------------------------------- TG-04 failed and partial runs


@pytest.mark.parametrize(
    "mutate",
    [
        _append("client.stderr", b"x"),
        lambda run: (run / ".run.lock").touch(),
        _summary_value,
        _symlink_payload,
    ],
    ids=["checksum", "lock", "result", "symlink"],
)
def test_tg04_nonverified_runs_suppress_report_and_keep_raw_bytes(fresh, mutate) -> None:
    run = fresh("captured_success")
    mutate(run)
    inspection = core().load_run(run)
    assert str(inspection.integrity) in ("failed", "unfinalized")
    assert inspection.report is None
    assert inspection.verification is None
    by_name = {artifact.name: artifact for artifact in inspection.snapshot.artifacts}
    # A readable regular payload remains inspectable as raw bytes.
    assert by_name["client.json"].data == (run / "client.json").read_bytes()
    if (run / "client.stderr").is_symlink():
        # Unsafe entries carry their issue and no content.
        assert by_name["client.stderr"].data is None
        assert by_name["client.stderr"].issue is not None
        assert str(by_name["client.stderr"].issue.code) == "PATH_UNSAFE"


def test_tg04_verified_failed_run_without_report_is_inspectable(fresh) -> None:
    inspection = core().load_run(fresh("connection_timeout"))
    assert str(inspection.integrity) == "verified"
    assert inspection.state == "failed"
    assert inspection.report is None
    assert inspection.manifest is not None


def test_tg04_verified_unreconciled_report_is_retained_for_labelled_display(fresh) -> None:
    for name in ("no_server", "gap"):
        inspection = core().load_run(fresh(name))
        assert str(inspection.integrity) == "verified"
        assert inspection.report is not None
        assert inspection.verification.result_verified is False


# ------------------------------------------------------------------ TG-06 read-only


FORBIDDEN_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


@pytest.mark.parametrize(
    "name", ["captured_success", "connection_timeout", "interrupted", "offline_plan"]
)
def test_tg06_loading_performs_no_mutation_process_or_network_activity(
    fresh, name, monkeypatch: pytest.MonkeyPatch
) -> None:
    from .conftest import view

    run = fresh(name)
    if name == "offline_plan":
        (run / ".run.lock").touch()  # also exercise the unfinalized path
    module, presenter = core(), view()
    before = tree_state(run)
    opened_flags: list[int] = []
    real_open = os.open

    def guarded_open(path, flags, *args, **kwargs):
        opened_flags.append(flags)
        return real_open(path, flags, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("viewer must not mutate, spawn or connect")

    monkeypatch.setattr(os, "open", guarded_open)
    for target, attribute in [
        (os, "unlink"),
        (os, "remove"),
        (os, "rename"),
        (os, "replace"),
        (os, "mkdir"),
        (os, "rmdir"),
        (os, "chmod"),
        (os, "utime"),
        (os, "truncate"),
        (os, "system"),
        (subprocess, "Popen"),
        (socket, "socket"),
        (socket, "create_connection"),
    ]:
        monkeypatch.setattr(target, attribute, forbidden)
    inspection = module.load_run(run)
    presenter.build_view(inspection)
    monkeypatch.undo()

    assert not [flags for flags in opened_flags if flags & FORBIDDEN_WRITE_FLAGS]
    assert tree_state(run) == before
    if name == "offline_plan":
        assert str(inspection.integrity) == "unfinalized"
        assert (run / ".run.lock").exists()  # never removed by the viewer


def test_tg06_lock_files_are_detected_without_being_opened(
    fresh, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = fresh("captured_success")
    (run / ".run.lock").write_text("held")
    module = core()
    names: list[str] = []
    real_open = os.open

    def recording_open(path, flags, *args, **kwargs):
        names.append(os.fspath(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    inspection = module.load_run(run)
    monkeypatch.undo()
    assert str(inspection.integrity) == "unfinalized"
    assert not [name for name in names if name.endswith(".run.lock")]


# --------------------------------------------------------------- TG-07 hostile inputs


def _oversize(name: str, size: int):
    def apply(run: Path) -> None:
        os.truncate(run / name, size)  # sparse; content irrelevant once size exceeds bound

    return apply


def _fifo(run: Path) -> None:
    (run / "client.stderr").unlink()
    os.mkfifo(run / "client.stderr")


def _many_entries(run: Path) -> None:
    for index in range(17):
        (run / f"junk{index}").write_text("x")


def _deep_json(run: Path) -> None:
    (run / "command.json").write_text("[" * 100 + "]" * 100)
    rehash(run)


def _nonfinite(run: Path) -> None:
    text = (run / "command.json").read_text()
    record = json.loads(text)
    record["returncode"] = 0
    text = json.dumps(record).replace('"returncode": 0', '"returncode": NaN')
    (run / "command.json").write_text(text)
    rehash(run)


def _invalid_utf8(run: Path) -> None:
    (run / "command.json").write_bytes(b'{"schema_version": "\xff"}')
    rehash(run)


def _duplicate_key(run: Path) -> None:
    (run / "command.json").write_text('{"execute": true, "execute": false}')
    rehash(run)


HOSTILE = [
    ("client_oversize", _oversize("client.json", 16 * 1024 * 1024 + 1), {"FILE_TOO_LARGE"}),
    ("manifest_oversize", _oversize("manifest.json", 1024 * 1024 + 1), {"FILE_TOO_LARGE"}),
    ("stderr_oversize", _oversize("client.stderr", 1024 * 1024 + 1), {"FILE_TOO_LARGE"}),
    ("fifo", _fifo, {"NONREGULAR_FILE"}),
    ("entries", _many_entries, {"ENTRY_LIMIT_EXCEEDED"}),
    ("deep_json", _deep_json, {"INVALID_JSON"}),
    ("nonfinite", _nonfinite, {"NONFINITE_VALUE"}),
    ("invalid_utf8", _invalid_utf8, {"INVALID_UTF8"}),
    ("duplicate_key", _duplicate_key, {"INVALID_JSON"}),
]


@pytest.mark.parametrize(("label", "mutate", "expected"), HOSTILE, ids=[h[0] for h in HOSTILE])
def test_tg07_hostile_inputs_fail_closed_and_bounded(fresh, label, mutate, expected) -> None:
    run = fresh("captured_success")
    mutate(run)
    with deadline(30):
        inspection = core().load_run(run)
    assert str(inspection.integrity) == "failed"
    assert expected & codes(inspection), codes(inspection)
    assert inspection.report is None
    for artifact in inspection.snapshot.artifacts:
        if artifact.data is not None:
            assert len(artifact.data) <= 16 * 1024 * 1024
    if label in ("client_oversize", "stderr_oversize", "manifest_oversize", "fifo"):
        name = {
            "client_oversize": "client.json",
            "stderr_oversize": "client.stderr",
            "manifest_oversize": "manifest.json",
            "fifo": "client.stderr",
        }[label]
        flagged = {a.name: a for a in inspection.snapshot.artifacts}.get(name)
        assert flagged is None or flagged.data is None  # no content for unsafe/oversize
    with deadline(60):
        assert cli_verify(run) == 3


def test_tg07_symlinked_root_is_refused(fresh, tmp_path: Path) -> None:
    run = fresh("captured_success")
    link = tmp_path / "link-to-run"
    os.symlink(run, link)
    inspection = core().load_run(link)
    assert str(inspection.integrity) == "failed"
    assert {"PATH_UNSAFE", "INPUT_MISSING"} & codes(inspection)


def test_tg07_traversal_entry_in_manifest_never_reads_outside_root(
    fresh, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = fresh("captured_success")
    secret = run.parent / "outside-secret.txt"
    secret.write_text("must not be read")

    def add_traversal(manifest: dict) -> None:
        manifest["artifacts"].append(
            {"path": "../outside-secret.txt", "size_bytes": 16, "sha256": "0" * 64}
        )

    edit_json(run, "manifest.json", add_traversal)
    module = core()
    real_open, opened = os.open, []

    def recording_open(path, flags, *args, **kwargs):
        opened.append(os.fspath(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    real_builtin_open = builtins.open

    def guarded_builtin_open(file, *args, **kwargs):
        if "outside-secret" in os.fspath(file):
            raise AssertionError("read outside the run root")
        return real_builtin_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_builtin_open)
    inspection = module.load_run(run)
    monkeypatch.undo()
    assert str(inspection.integrity) == "failed"
    assert {"SCHEMA_INVALID", "PATH_UNSAFE", "ARTIFACT_COVERAGE_MISMATCH"} & codes(inspection)
    assert not [name for name in opened if "outside-secret" in name or ".." in name]


# ------------------------------------------------------------------- R-12 platform


def test_r12_windows_is_refused_before_touching_the_filesystem(
    fresh, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = fresh("captured_success")
    module = core()

    def forbidden(*args, **kwargs):
        raise AssertionError("no filesystem access on unsupported platform")

    monkeypatch.setattr(sys, "platform", "win32")
    for attribute in ("open", "stat", "lstat", "listdir", "scandir"):
        monkeypatch.setattr(os, attribute, forbidden)
    inspection = module.load_run(run)
    monkeypatch.undo()
    assert str(inspection.integrity) == "failed"
    assert codes(inspection) == {"PLATFORM_UNSUPPORTED"}


# ------------------------------------------------------- R-13 internal errors contained


def test_r13_unexpected_exception_becomes_internal_error_without_raw_text(
    fresh, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = fresh("captured_success")
    module = core()

    def explode(*args, **kwargs):
        raise RuntimeError("SECRET-RAW-DATA-10.99.0.10")

    monkeypatch.setattr(json, "loads", explode)
    inspection = module.load_run(run)
    monkeypatch.undo()
    assert str(inspection.integrity) == "failed"
    assert codes(inspection) == {"INTERNAL_ERROR"}
    for issue in inspection.issues:
        assert "SECRET-RAW-DATA" not in issue.message
        assert len(issue.message) <= 512


def test_r13_base_exceptions_propagate(fresh, monkeypatch: pytest.MonkeyPatch) -> None:
    run = fresh("captured_success")
    module = core()

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(json, "loads", interrupt)
    with pytest.raises(KeyboardInterrupt):
        module.load_run(run)


def test_issue_messages_are_bounded(fresh) -> None:
    run = fresh("captured_success")
    (run / ("x" * 200)).write_text("x")
    inspection = core().load_run(run)
    assert inspection.issues
    for issue in inspection.issues:
        assert len(issue.message) <= 512
        assert issue.path is None or "/" not in issue.path


# --------------------------------------------------------------------- R-14 progress


def test_r14_progress_is_bounded_monotonic_and_complete(fresh) -> None:
    run = fresh("four_omit")
    calls: list[tuple[int, int]] = []
    inspection = core().load_run(run, progress=lambda done, total: calls.append((done, total)))
    assert str(inspection.integrity) == "verified"
    assert 1 <= len(calls) <= 16
    totals = {total for _, total in calls}
    assert len(totals) == 1
    total = totals.pop()
    assert total >= len([name for name in PAYLOADS if (run / name).exists()])
    done = [value for value, _ in calls]
    assert done == sorted(done)
    assert all(0 <= value <= total for value in done)
    assert calls[-1] == (total, total)


# ----------------------------------------------------------------- R-15 cancellation


def test_r15_preset_cancel_opens_nothing(fresh, monkeypatch: pytest.MonkeyPatch) -> None:
    run = fresh("captured_success")
    module = core()
    event = threading.Event()
    event.set()
    opened: list[str] = []
    real_open = os.open

    def recording_open(path, flags, *args, **kwargs):
        opened.append(os.fspath(path))
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", recording_open)
    inspection = module.load_run(run, cancel=event)
    monkeypatch.undo()
    assert str(inspection.integrity) == "cancelled"
    assert "CANCELLED" in codes(inspection)
    assert opened == []


def test_r15_cancel_during_capture_discards_results(fresh) -> None:
    run = fresh("four_omit")
    event = threading.Event()

    def progress(done: int, total: int) -> None:
        if done >= 1:
            event.set()

    inspection = core().load_run(run, cancel=event, progress=progress)
    assert str(inspection.integrity) == "cancelled"
    assert "CANCELLED" in codes(inspection)
    assert inspection.verification is None
    assert inspection.report is None


def test_r15_cancelled_load_leaves_no_open_descriptors(fresh) -> None:
    run = fresh("four_omit")
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.exists():
        pytest.skip("descriptor accounting needs /proc (Linux)")
    before = set(os.listdir(fd_dir))
    event = threading.Event()
    core().load_run(run, cancel=event, progress=lambda done, total: event.set())
    core().load_run(run)
    assert set(os.listdir(fd_dir)) <= before | set()  # nothing leaked by either load
