"""Independent regressions for Claude's review findings P2-F1 and CORE-1.

P2-F1 (Phase 2 contract: "File writes are bounded"; "Cleanup/failure paths finalize
whatever evidence is available"): a client.json whose derived summary exceeds 16 MiB must
end as a finalized, verifiable failed run, never as a permanently `running` directory. A
finalization failure must leave an honest terminal manifest, not `running`.

CORE-1 (GUI contract R-4; verify parity R-1): evidence provenance is a display concern. A run
the parser and runner accept must verify, through both `diaglab verify` and load_run, even
when an interval `sum` window differs from its streams' window within the parser's own
1e-6 s tolerance; evidence must then cite the `sum` fields the parser actually used.

CHART-1 (GUI contract: omitted intervals hatched as warm-up, excluded from retained data;
proposed R-27): iperf3 restarts its interval clock after --omit, so warm-up windows and the
first retained windows carry the same raw start/end. The timeline must not draw them on the
same time span. Retained points keep their raw parser times (the axis iperf3 and the summary
use); warm-up points precede them on the display axis with their durations unchanged.

FAIL-1 (GUI contract: "Verified failed/interrupted runs ... show unavailable metrics, logs,
state and failure reason"): the recorded failure reason must be visible in the run's
status or summary, not only as an event message inside the log tab.

Round 3 (Gemini section 1.3 requests, adapted to accepted parser contracts):
ZERO-1: a measured zero-byte receiver interval is a value (0 bit/s, with evidence), never
"unavailable" and never a line break. SHIFT-1: R-27's warm-up shift is computed per series;
the client and the embedded server timestamp independently, so their series may need
different shifts. Different warm-up counts per stream are NOT constructible: the parser
requires one omitted flag per parallel interval (parser.py OMIT_METADATA_MISMATCH).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest

from diaglab.artifacts.store import ArtifactStore
from diaglab.exceptions import ArtifactIntegrityError
from diaglab.run import verify_run
from diaglab.traffic import runner as runner_module

from .conftest import core, view
from .runs import SOURCE_IP, RunBuilder, cli_verify, resolve_pointer, synthetic_document

LIMIT = 16 * 1024 * 1024

# ---------------------------------------------------------------------------- P2-F1


@pytest.fixture(scope="module")
def oversized_summary_run(tmp_path_factory: pytest.TempPathFactory, base_config: dict):
    """client.json ~12.3 MiB (under the 16 MiB output cap) whose summary would be ~17 MiB."""
    builder = RunBuilder(tmp_path_factory.mktemp("p2f1"), base_config)
    document = synthetic_document(streams=4, retained=7600)
    text = json.dumps(document)
    assert len(text.encode()) < LIMIT  # the runner's output cap accepts this client output
    return builder._execute("p2f1", text, duration_s=7600, streams=4)


def test_p2f1_oversized_summary_ends_as_finalized_failed_run(oversized_summary_run) -> None:
    run = oversized_summary_run
    names = set(os.listdir(run))
    assert ".run.lock" not in names
    assert "traffic_summary.json" not in names  # no partial or oversized summary written
    assert "checksums.json" in names
    for name in names:
        assert (run / name).stat().st_size <= LIMIT, name
    manifest = json.loads((run / "manifest.json").read_text())
    command = json.loads((run / "command.json").read_text())
    assert manifest["state"] == "failed"
    assert manifest["cleanup"]["status"] == "verified"
    assert manifest["eligibility"]["status"] == "rejected"
    assert command["failure_reason"] == "SUMMARY_OUTPUT_LIMIT_EXCEEDED"
    assert manifest["eligibility"]["reasons"] == ["SUMMARY_OUTPUT_LIMIT_EXCEEDED"]
    assert command["returncode"] == 0
    assert command["transfer_completed"] is False
    assert command["result_verified"] is False
    failed = [event for event in manifest["events"] if event["name"] == "RUN_FAILED"]
    assert [event.get("message") for event in failed] == ["SUMMARY_OUTPUT_LIMIT_EXCEEDED"]


def test_p2f1_oversized_summary_run_verifies_as_intact_failed_evidence(
    oversized_summary_run,
) -> None:
    result = verify_run(oversized_summary_run)
    assert (result.verified, result.state) == (True, "failed")
    assert (result.transfer_completed, result.result_verified) == (False, False)
    assert cli_verify(oversized_summary_run) == 0
    inspection = core().load_run(oversized_summary_run)
    assert str(inspection.integrity) == "verified"
    assert inspection.report is None
    run_view = view().build_view(inspection)
    assert run_view.series == ()


def test_p2f1_largest_fitting_summary_still_completes_and_verifies(large_run) -> None:
    summary = large_run / "traffic_summary.json"
    assert LIMIT * 0.8 < summary.stat().st_size <= LIMIT  # genuinely near the bound
    result = verify_run(large_run)
    assert (result.state, result.result_verified) == ("completed", True)
    assert cli_verify(large_run) == 0


def test_p2f1_finalization_failure_leaves_terminal_not_running_manifest(
    tmp_path: Path, base_config: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    builder = RunBuilder(tmp_path / "finalize", base_config)
    real_digest = ArtifactStore.digest

    def failing_digest(store, name, **kwargs):
        if name == "client.json":
            raise ArtifactIntegrityError("injected finalization failure")
        return real_digest(store, name, **kwargs)

    monkeypatch.setattr(ArtifactStore, "digest", failing_digest)
    monkeypatch.setattr(runner_module, "resolve_source", lambda context: SOURCE_IP)
    monkeypatch.setattr(runner_module, "probe_server", lambda context, source: None)
    document = json.dumps(synthetic_document(streams=1, retained=3))
    run = builder.root / "finalize"
    # _execute swallows the propagated error; we assert the on-disk outcome instead.
    builder._execute("finalize", document, duration_s=3, streams=1)
    monkeypatch.undo()

    assert ".run.lock" not in os.listdir(run)
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["state"] == "failed"  # never left `running`
    assert manifest["eligibility"]["status"] == "rejected"
    assert "FINALIZATION_FAILED" in manifest["eligibility"]["reasons"]
    assert any(
        event["name"] == "RUN_FAILED" and event.get("message") == "FINALIZATION_FAILED"
        for event in manifest["events"]
    )
    # Unfinalized payload coverage cannot verify, but it is reported as a failure, never as
    # "not finalized" and never as success.
    inspection = core().load_run(run)
    assert str(inspection.integrity) == "failed"
    assert "RUN_UNFINALIZED" not in {str(issue.code) for issue in inspection.issues}
    assert cli_verify(run) in (2, 3)


def test_p2f1_finalization_failure_propagates_to_the_caller(
    tmp_path: Path, base_config: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    from diaglab.config import ExperimentConfig
    from diaglab.run import run_experiment

    from .runs import config_dict

    builder = RunBuilder(tmp_path / "propagate", base_config)
    real_digest = ArtifactStore.digest

    def failing_digest(store, name, **kwargs):
        if name == "client.json":
            raise ArtifactIntegrityError("injected finalization failure")
        return real_digest(store, name, **kwargs)

    document = tmp_path / "doc.json"
    document.write_text(json.dumps(synthetic_document(streams=1, retained=3)))
    monkeypatch.setenv("MOCK_DOC", str(document))
    monkeypatch.setenv("MOCK_RC", "0")
    monkeypatch.delenv("MOCK_BEHAVIOR", raising=False)
    monkeypatch.delenv("MOCK_SIGNAL_REPORT", raising=False)
    monkeypatch.setattr(ArtifactStore, "digest", failing_digest)
    monkeypatch.setattr(runner_module, "resolve_source", lambda context: SOURCE_IP)
    monkeypatch.setattr(runner_module, "probe_server", lambda context, source: None)
    config = ExperimentConfig.from_dict(config_dict(base_config, duration_s=3, streams=1))
    with pytest.raises(ArtifactIntegrityError):
        run_experiment(config, tmp_path / "out", execute=True, executable=str(builder.mock))


# --------------------------------------------------------------------------- CORE-1


@pytest.fixture(scope="module")
def jittered_sum_run(tmp_path_factory: pytest.TempPathFactory, base_config: dict) -> Path:
    builder = RunBuilder(tmp_path_factory.mktemp("core1"), base_config)
    return builder.synthetic("jitter", streams=4, retained=3, sum_offset_s=5e-7)


def test_core1_runner_accepts_sum_window_within_parser_tolerance(jittered_sum_run) -> None:
    manifest = json.loads((jittered_sum_run / "manifest.json").read_text())
    command = json.loads((jittered_sum_run / "command.json").read_text())
    assert manifest["state"] == "completed"
    assert command["result_verified"] is True


def test_core1_verify_accepts_what_the_runner_accepted(jittered_sum_run) -> None:
    result = verify_run(jittered_sum_run)
    assert (result.verified, result.state, result.result_verified) == (True, "completed", True)
    assert cli_verify(jittered_sum_run) == 0


def test_core1_viewer_verifies_and_cites_the_sum_window_used(jittered_sum_run) -> None:
    inspection = core().load_run(jittered_sum_run)
    assert str(inspection.integrity) == "verified", inspection.issues
    client = json.loads(
        next(a.data for a in inspection.snapshot.artifacts if a.name == "client.json")
    )
    run_view = view().build_view(inspection)
    aggregates = [
        series
        for series in run_view.series
        if "goodput" in series.label.casefold() and "aggregate" in series.label.casefold()
    ]
    assert len(aggregates) == 1
    for point in aggregates[0].points:
        inputs = [p for ref in point.evidence for p in (ref.json_pointer, *ref.inputs) if p]
        starts = [resolve_pointer(client, p) for p in inputs if p.endswith("/start")]
        ends = [resolve_pointer(client, p) for p in inputs if p.endswith("/end")]
        total = sum(resolve_pointer(client, p) for p in inputs if p.endswith("/bytes"))
        assert starts == [point.start_s] and ends == [point.end_s]
        assert math.isclose(point.value, total * 8 / (ends[0] - starts[0]), rel_tol=1e-12)


def test_core1_provenance_never_downgrades_verified_integrity(
    fresh, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even if evidence resolution itself fails, verification outcome must not change:
    integrity and verify_run stay verified; only evidence may become unavailable.
    Written after reading the implementation (review regression): it fault-injects the
    core's provenance step by name, so a rename must update this test, not skip it."""
    run = fresh("four_omit")
    module = core()
    names = [name for name in dir(module) if "provenance" in name.casefold()]
    assert names, "provenance step not found; update this review regression"
    for name in names:
        monkeypatch.setattr(module, name, _raise_key_error)
    result = verify_run(run)
    inspection = module.load_run(run)
    monkeypatch.undo()
    assert result.verified is True
    assert str(inspection.integrity) == "verified"


def _raise_key_error(*args, **kwargs):
    raise KeyError("injected provenance failure")


def test_core1_runner_and_verify_agree_on_every_matrix_run(matrix) -> None:
    for name, run in matrix.items():
        manifest = json.loads((run / "manifest.json").read_text())
        if manifest["state"] == "running":
            continue
        assert verify_run(run).verified is True, name


# ---------------------------------------------------------------------------- CHART-1


def _raw_window(client: dict, point) -> tuple[float, float]:
    """The raw JSON start/end behind a chart point, resolved from its evidence bytes."""
    for ref in point.evidence:
        pointers = [p for p in (ref.json_pointer, *ref.inputs) if p]
        starts = [p for p in pointers if p.endswith("/start")]
        ends = [p for p in pointers if p.endswith("/end")]
        if starts and ends:
            return resolve_pointer(client, starts[0]), resolve_pointer(client, ends[0])
        for pointer in pointers:
            for candidate in (pointer, pointer.rsplit("/", 1)[0]):
                target = resolve_pointer(client, candidate)
                if isinstance(target, dict) and {"start", "end"} <= target.keys():
                    return target["start"], target["end"]
    raise AssertionError(f"no raw window in evidence of {point}")


def _omit_view(fresh):
    inspection = core().load_run(fresh("four_omit"))
    assert str(inspection.integrity) == "verified", inspection.issues
    client = json.loads(
        next(a.data for a in inspection.snapshot.artifacts if a.name == "client.json")
    )
    run_view = view().build_view(inspection)
    assert run_view.series
    return client, run_view


def test_chart1_fixture_reproduces_the_iperf3_clock_restart(fresh) -> None:
    client, run_view = _omit_view(fresh)
    windows = [(i["sum"]["start"], i["sum"]["omitted"]) for i in client["intervals"]]
    assert windows[:3] == [(0.0, True), (1.0, True), (0.0, False)]


def test_chart1_warmup_never_shares_time_with_retained_points(fresh) -> None:
    _, run_view = _omit_view(fresh)
    for series in run_view.series:
        warm = [p for p in series.points if p.omitted]
        kept = [p for p in series.points if not p.omitted]
        assert warm and kept, series.label
        assert max(p.end_s for p in warm) <= min(p.start_s for p in kept) + 1e-9, series.label
        spans = sorted((p.start_s, p.end_s) for p in series.points)
        for (_, end), (start, _) in zip(spans, spans[1:], strict=False):
            assert end <= start + 1e-9, (series.label, spans)


def test_chart1_retained_points_keep_raw_parser_time(fresh) -> None:
    client, run_view = _omit_view(fresh)
    for series in run_view.series:
        for point in (p for p in series.points if not p.omitted):
            assert (point.start_s, point.end_s) == _raw_window(client, point), series.label


def test_chart1_warmup_points_keep_raw_duration_and_order(fresh) -> None:
    client, run_view = _omit_view(fresh)
    for series in run_view.series:
        warm = [p for p in series.points if p.omitted]
        offsets = set()
        for point in warm:
            start, end = _raw_window(client, point)
            assert math.isclose(point.end_s - point.start_s, end - start, abs_tol=1e-9)
            offsets.add(round(point.start_s - start, 9))
        assert len(offsets) == 1, (series.label, offsets)  # one constant shift, no reorder


def test_chart1_runs_without_omit_are_plotted_at_raw_time(fresh) -> None:
    inspection = core().load_run(fresh("captured_success"))
    client = json.loads(
        next(a.data for a in inspection.snapshot.artifacts if a.name == "client.json")
    )
    for series in view().build_view(inspection).series:
        for point in series.points:
            assert (point.start_s, point.end_s) == _raw_window(client, point), series.label


# ---------------------------------------------------------------------------- FAIL-1


@pytest.mark.parametrize("name", ["connection_timeout", "interrupted", "no_server", "gap"])
def test_fail1_failure_reason_is_shown_outside_the_event_log(fresh, name: str) -> None:
    run = fresh(name)
    reason = json.loads((run / "command.json").read_text())["failure_reason"]
    assert reason, "fixture must be a failed or interrupted run"
    inspection = core().load_run(run)
    assert str(inspection.integrity) == "verified", inspection.issues
    run_view = view().build_view(inspection)
    shown = [run_view.traffic_text, *(value.text for value in run_view.summary)]
    assert any(reason in text for text in shown), (reason, shown)


# ---------------------------------------------------------------- ZERO-1 / SHIFT-1


def _build(tmp_path: Path, base_config: dict, name: str, document: dict) -> Path:
    builder = RunBuilder(tmp_path / "builder", base_config)
    test_start = document["start"]["test_start"]
    run = builder._execute(
        name,
        json.dumps(document),
        duration_s=test_start["duration"],
        streams=test_start["num_streams"],
        omit_s=test_start["omit"],
    )
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["state"] == "completed", manifest["eligibility"]  # fixture sanity
    return run


def _rate(record: dict) -> None:
    record["bits_per_second"] = record["bytes"] * 8 / (record["end"] - record["start"])


def _zero_receiver_epoch(document: dict, epoch: int) -> None:
    """A receiver stall: the embedded server measured 0 bytes in one retained interval.
    Every receiver total (server and the client's copy) drops by the same bytes, so the
    document stays self-consistent; the sender side is unchanged."""
    server = document["server_output_json"]
    rows = server["intervals"][epoch]["streams"]
    removed = [row["bytes"] for row in rows]
    for row in [*rows, server["intervals"][epoch]["sum"]]:
        row["bytes"] = 0
        row["bits_per_second"] = 0.0
    receivers = [
        [stream["receiver"] for stream in server["end"]["streams"]],
        [stream["receiver"] for stream in document["end"]["streams"]],
    ]
    for side in receivers:
        for record, value in zip(side, removed, strict=True):
            record["bytes"] -= value
            _rate(record)
    for total in (server["end"]["sum_received"], document["end"]["sum_received"]):
        total["bytes"] -= sum(removed)
        _rate(total)


def test_zero1_zero_byte_receiver_interval_is_a_measured_zero(
    tmp_path: Path, base_config: dict
) -> None:
    document = synthetic_document(streams=4, retained=4)
    _zero_receiver_epoch(document, 1)
    run = _build(tmp_path, base_config, "zero", document)
    inspection = core().load_run(run)
    assert str(inspection.integrity) == "verified", inspection.issues
    client = json.loads(
        next(a.data for a in inspection.snapshot.artifacts if a.name == "client.json")
    )
    run_view = view().build_view(inspection)
    goodput = [s for s in run_view.series if s.label.startswith("Receiver goodput")]
    assert len(goodput) == 5  # four flows plus the aggregate
    for series in goodput:
        assert [p.value == 0 for p in series.points] == [False, True, False, False]
        zero, after = series.points[1], series.points[2]
        assert zero.value == 0.0 and zero.value is not None, series.label
        assert not zero.break_before and not after.break_before, series.label  # data, not a gap
        pointers = [p for ref in zero.evidence for p in (ref.json_pointer, *ref.inputs) if p]
        assert [resolve_pointer(client, p) for p in pointers if p.endswith("/bytes")] == [0]
    assert view().format_value(0.0, "bps") == "0.000 Mbit/s"
    headline = run_view.summary[0]
    assert headline.value is not None and headline.unavailable_reason is None
    assert not headline.text.startswith("Unavailable")


def test_shift1_warmup_shift_is_computed_per_series(tmp_path: Path, base_config: dict) -> None:
    """The embedded server's warm-up windows end 0.4 ms later than the client's, as two
    independently clocked endpoints may report. Each series is shifted by its own amount,
    so no series overlaps itself; a single run-wide shift would leave receiver warm-up
    overlapping the first retained receiver interval."""
    offset = 0.0004
    document = synthetic_document(streams=4, retained=4, omitted=2)
    for epoch in document["server_output_json"]["intervals"][:2]:
        for row in [*epoch["streams"], epoch["sum"]]:
            assert row["omitted"] is True
            row["start"] += offset
            row["end"] += offset
    run = _build(tmp_path, base_config, "skew", document)
    inspection = core().load_run(run)
    assert str(inspection.integrity) == "verified", inspection.issues
    shifts = {}
    for series in view().build_view(inspection).series:
        warm = [p for p in series.points if p.omitted]
        kept = [p for p in series.points if not p.omitted]
        assert warm and kept, series.label
        assert max(p.end_s for p in warm) <= min(p.start_s for p in kept), series.label
        for point in kept:
            assert (point.start_s, point.end_s) == (point.raw_start_s, point.raw_end_s)
        for point in warm:
            assert math.isclose(
                point.end_s - point.start_s, point.raw_end_s - point.raw_start_s, abs_tol=1e-12
            )
        shifts[series.label] = {round(p.start_s - p.raw_start_s, 9) for p in warm}
        assert len(shifts[series.label]) == 1, series.label
    receiver = {s for label, v in shifts.items() if label.startswith("Receiver") for s in v}
    sender = {s for label, v in shifts.items() if not label.startswith("Receiver") for s in v}
    assert receiver == {round(-2.0 - offset, 9)} and sender == {-2.0}  # fixture exercises both
