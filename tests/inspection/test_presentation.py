"""TG-01 value fidelity, TG-05 missing data, TG-08 evidence linkage and R-3..R-11 for
diaglab.presentation, written from docs/GUI_CONTRACTS.md + R-1..R-23 before implementation.

Oracles are independent of diaglab: raw values come from json.loads of the snapshot bytes
and an RFC 6901 resolver in tests/inspection/runs.py; goodput is re-derived here as
bytes * 8 / (end - start). Values are located by unit and evidence, not by widget layout.
"""

from __future__ import annotations

import builtins
import json
import math
import os
import socket
import subprocess
from pathlib import Path
from typing import Any

import pytest

from .conftest import core, view
from .runs import resolve_pointer

GOODPUT_DERIVATIONS = {"goodput_bps", "AGGREGATE_DERIVED_FROM_FLOWS"}

# ---------------------------------------------------------------------------- helpers


def load(fresh, name: str):
    inspection = core().load_run(fresh(name))
    return inspection, view().build_view(inspection)


def documents(inspection) -> dict[str, Any]:
    """Independently parsed snapshot artifacts (events.jsonl -> list of records)."""
    parsed: dict[str, Any] = {}
    for artifact in inspection.snapshot.artifacts:
        if artifact.data is None:
            continue
        if artifact.name == "events.jsonl":
            parsed[artifact.name] = [json.loads(line) for line in artifact.data.splitlines()]
        elif artifact.name.endswith(".json"):
            parsed[artifact.name] = json.loads(artifact.data)
        else:
            parsed[artifact.name] = artifact.data
    return parsed


def pointers(refs) -> list[tuple[str, str]]:
    found = []
    for ref in refs:
        found.append((ref.artifact, ref.json_pointer))
        found.extend((ref.artifact, item) for item in ref.inputs)
    return found


def derived_goodput(docs: dict[str, Any], refs) -> float:
    """bytes * 8 / (end - start) from the referenced raw fields; sums bytes over flows
    when the aggregate was derived (R-4)."""
    found = [(artifact, p) for artifact, p in pointers(refs) if p]
    byte_values = [resolve_pointer(docs[a], p) for a, p in found if p.endswith("/bytes")]
    starts = [resolve_pointer(docs[a], p) for a, p in found if p.endswith("/start")]
    ends = [resolve_pointer(docs[a], p) for a, p in found if p.endswith("/end")]
    assert byte_values and starts and ends, f"goodput inputs incomplete: {found}"
    assert len(set(starts)) == 1 and len(set(ends)) == 1, "mixed windows in one value"
    return sum(byte_values) * 8 / (ends[0] - starts[0])


def all_display_values(run_view) -> list:
    values = list(run_view.summary) + list(run_view.collectors)
    for row in run_view.flows:
        values.extend(row.values)
    return values


def find_summary(run_view, keyword: str, unit: str | None = None):
    matches = [
        value
        for value in run_view.summary
        if keyword in value.label.casefold() and (unit is None or value.unit == unit)
    ]
    assert len(matches) == 1, [(v.label, v.unit) for v in run_view.summary]
    return matches[0]


def goodput_series(run_view) -> list:
    return [s for s in run_view.series if "goodput" in s.label.casefold()]


def rtt_series(run_view) -> list:
    return [s for s in run_view.series if s.unit == "µs"]


# ------------------------------------------------------------------- R-5 formatting


@pytest.mark.parametrize(
    ("value", "unit", "reason", "expected"),
    [
        (941_523_456.0, "bps", None, "941.523 Mbit/s"),
        (8_000_000, "bps", None, "8.000 Mbit/s"),
        (0.0, "bps", None, "0.000 Mbit/s"),
        (30.000_123, "s", None, "30.000 s"),
        (0.5, "s", None, "0.500 s"),
        (450, "us", None, "450.000 µs"),
        (1234.5678, "us", None, "1234.568 µs"),
        (3_542_089_728, "bytes", None, "3542089728 B"),
        (0, "count", None, "0"),
        (17, "count", None, "17"),
        (None, "us", "TCP_INFO_UNAVAILABLE", "Unavailable: TCP_INFO_UNAVAILABLE"),
        (None, "bps", None, "Unavailable: NOT_RECORDED"),
    ],
)
def test_r5_format_value(value, unit, reason, expected) -> None:
    assert view().format_value(value, unit, reason=reason) == expected


@pytest.mark.parametrize(
    ("value", "unit"),
    [(1.0, "Mbps"), (1.0, "ms"), (True, "count"), (False, "bps"), (1.5, "bytes"), (2.0, "count")],
)
def test_r5_format_value_rejects_unknown_units_and_bad_types(value, unit) -> None:
    with pytest.raises(ValueError):
        view().format_value(value, unit)


def test_r5_display_units_are_the_closed_display_set(fresh) -> None:
    for name in ("captured_success", "four_omit", "four_derived"):
        _, run_view = load(fresh, name)
        for value in all_display_values(run_view):
            assert value.unit in {"Mbit/s", "s", "µs", "B", "count", ""}, value
        for series in run_view.series:
            assert series.unit in {"Mbit/s", "µs"}, series.label


# ------------------------------------------------------------- TG-01 value fidelity


def test_tg01_summary_goodput_is_receiver_goodput_from_embedded_server(fresh) -> None:
    inspection, run_view = load(fresh, "captured_success")
    docs = documents(inspection)
    goodput = find_summary(run_view, "goodput", "Mbit/s")
    raw = docs["client.json"]["server_output_json"]["end"]["sum_received"]
    independent = raw["bytes"] * 8 / (raw["end"] - raw["start"])
    assert goodput.value == inspection.report.receiver.computed_bps
    assert math.isclose(goodput.value, independent, rel_tol=1e-12)
    assert goodput.text == f"{goodput.value / 1e6:.3f} Mbit/s"
    assert all(
        p.startswith("/server_output_json/end/sum_received")
        for _, p in pointers(goodput.evidence)
        if p
    )
    assert {ref.derivation for ref in goodput.evidence} <= GOODPUT_DERIVATIONS


def test_tg01_residual_and_retransmits_match_raw_endpoints(fresh) -> None:
    for name in ("captured_success", "four_omit"):
        inspection, run_view = load(fresh, name)
        client = documents(inspection)["client.json"]
        residual = find_summary(run_view, "residual", "B")
        expected = (
            client["end"]["sum_sent"]["bytes"]
            - client["server_output_json"]["end"]["sum_received"]["bytes"]
        )
        assert residual.value == inspection.report.endpoint_byte_residual == expected
        assert residual.text == f"{expected} B"
        retransmits = find_summary(run_view, "retransmit", "count")
        assert retransmits.value == client["end"]["sum_sent"]["retransmits"]


def test_tg01_quality_flags_are_all_displayed(fresh) -> None:
    for name in ("captured_success", "no_server", "gap", "four_derived"):
        inspection, run_view = load(fresh, name)
        shown = find_summary(run_view, "quality")
        for flag in inspection.report.quality_flags:
            assert flag in shown.text, (name, flag)
    # The captured run is result_verified yet still carries anomaly flags; they stay visible.
    inspection, run_view = load(fresh, "captured_success")
    assert {"REPORTED_DURATION_MISMATCH", "SENDER_FLAG_MISMATCH"} <= set(
        inspection.report.quality_flags
    )


def test_tg01_flow_rows_match_raw_per_flow_values(fresh) -> None:
    for name, streams in (("captured_success", 1), ("four_omit", 4)):
        inspection, run_view = load(fresh, name)
        client = documents(inspection)["client.json"]
        sockets = [item["socket"] for item in client["start"]["connected"]]
        assert sorted(row.socket_id for row in run_view.flows) == sorted(sockets)
        assert len(run_view.flows) == streams
        raw_by_socket = {
            item["sender"]["socket"]: item["sender"] for item in client["end"]["streams"]
        }
        for row in run_view.flows:
            mean = [
                value
                for value in row.values
                if value.unit == "µs" and "mean" in value.label.casefold()
            ]
            assert len(mean) == 1, [(v.label, v.unit) for v in row.values]
            assert mean[0].value == raw_by_socket[row.socket_id]["mean_rtt"]
            assert mean[0].text == f"{mean[0].value:.3f} µs"


def test_tg01_four_stream_aggregate_is_not_double_counted(fresh) -> None:
    inspection, run_view = load(fresh, "four_omit")
    docs = documents(inspection)
    goodput = find_summary(run_view, "goodput", "Mbit/s")
    server = docs["client.json"]["server_output_json"]["end"]
    per_flow = sum(item["receiver"]["bytes"] for item in server["streams"])
    assert per_flow == server["sum_received"]["bytes"]
    window = server["sum_received"]["end"] - server["sum_received"]["start"]
    assert math.isclose(goodput.value, per_flow * 8 / window, rel_tol=1e-12)


# ----------------------------------------------- R-3 chart direction / R-8 breaks


def test_r3_goodput_points_come_only_from_receiver_intervals(fresh) -> None:
    for name, streams in (("captured_success", 1), ("four_omit", 4), ("four_derived", 4)):
        inspection, run_view = load(fresh, name)
        docs = documents(inspection)
        series = goodput_series(run_view)
        assert series, name
        if streams == 4:
            assert len(series) == streams + 1  # each flow plus one distinct aggregate
        for item in series:
            assert item.unit == "Mbit/s"
            assert "sender" not in item.label.casefold()
            for point in item.points:
                found = [p for _, p in pointers(point.evidence) if p]
                assert found and all(p.startswith("/server_output_json/intervals/") for p in found)
                if point.value is not None:
                    assert math.isclose(
                        point.value, derived_goodput(docs, point.evidence), rel_tol=1e-12
                    )


def test_r3_sender_series_are_labelled_sender(fresh) -> None:
    for name in ("captured_success", "four_omit", "no_server"):
        _, run_view = load(fresh, name)
        for item in run_view.series:
            if item.unit != "Mbit/s":
                continue
            client_side = [
                p
                for point in item.points
                for _, p in pointers(point.evidence)
                if p.startswith("/intervals/")
            ]
            if client_side:
                assert "sender" in item.label.casefold()
                assert "goodput" not in item.label.casefold()


def test_r3_no_goodput_series_without_receiver_intervals(fresh) -> None:
    _, run_view = load(fresh, "no_server")
    assert goodput_series(run_view) == []
    assert "traffic result unverified" in run_view.traffic_text.casefold()


def test_r3_rtt_series_are_per_flow_sender_side_only(fresh) -> None:
    inspection, run_view = load(fresh, "four_omit")
    docs = documents(inspection)
    series = rtt_series(run_view)
    assert len(series) == 4  # one per flow, no aggregate RTT
    for item in series:
        assert "latency" not in item.label.casefold()
        for point in item.points:
            found = [(a, p) for a, p in pointers(point.evidence) if p]
            assert found
            for artifact, pointer in found:
                assert pointer.startswith("/intervals/") and "/streams/" in pointer
                assert "/sum" not in pointer
                assert pointer.endswith("/rtt")
                assert point.value == resolve_pointer(docs[artifact], pointer)


def test_r8_omitted_warmup_is_marked_and_broken_from_retained_data(fresh) -> None:
    _, run_view = load(fresh, "four_omit")
    for item in goodput_series(run_view):
        flags = [point.omitted for point in item.points]
        assert flags == [True, True, False, False, False, False, False]
        assert [point.break_before for point in item.points] == [
            False,
            False,
            True,
            False,
            False,
            False,
            False,
        ]


def test_r8_interval_gap_breaks_the_line(fresh) -> None:
    _, run_view = load(fresh, "gap")
    series = goodput_series(run_view)
    assert series
    for item in series:
        breaks = [point.break_before for point in item.points]
        assert breaks == [False, False, True, False]


def test_r8_null_values_break_and_are_never_zero(fresh) -> None:
    _, run_view = load(fresh, "four_derived")
    for item in run_view.series:
        previous = None
        for index, point in enumerate(item.points):
            if item.unit == "µs":
                assert point.value is None or point.value != 0
            if index and previous is not None and previous.value is None:
                assert point.break_before is True
            previous = point


# ----------------------------------------------------------- TG-05 missing values


def test_tg05_unavailable_rtt_is_reasoned_not_zero(fresh) -> None:
    _, run_view = load(fresh, "four_derived")
    for row in run_view.flows:
        rtt = [value for value in row.values if value.unit == "µs"]
        assert rtt
        for value in rtt:
            assert value.value is None
            assert value.unavailable_reason == "TCP_INFO_UNAVAILABLE"
            assert value.text == "Unavailable: TCP_INFO_UNAVAILABLE"


def test_tg05_every_missing_value_says_unavailable(fresh) -> None:
    for name in ("captured_success", "four_derived", "connection_timeout", "no_server"):
        _, run_view = load(fresh, name)
        for value in all_display_values(run_view):
            if value.value is None:
                assert value.text.startswith("Unavailable: "), (name, value)
                assert value.unavailable_reason
            else:
                assert value.unavailable_reason is None


def test_r7_collectors_are_listed_as_not_implemented(fresh, base_config) -> None:
    _, run_view = load(fresh, "captured_success")
    names = [item["name"] for item in base_config["telemetry"]["collectors"]]
    assert len(run_view.collectors) == len(names)
    for value in run_view.collectors:
        assert value.value is None
        assert value.unavailable_reason == "NOT_IMPLEMENTED_PHASE2"
        assert value.text == "Unavailable: NOT_IMPLEMENTED_PHASE2"
    for name in names:
        assert sum(name in value.label for value in run_view.collectors) == 1, name


# ------------------------------------------------------------ TG-08 evidence links


def test_tg08_every_evidence_reference_resolves_in_the_snapshot(fresh) -> None:
    for name in ("captured_success", "four_omit", "four_derived", "gap"):
        inspection, run_view = load(fresh, name)
        docs = documents(inspection)
        hashes = {a.name: a.sha256 for a in inspection.snapshot.artifacts}
        carriers = [(v.value, v.evidence) for v in all_display_values(run_view)]
        carriers += [(p.value, p.evidence) for s in run_view.series for p in s.points]
        checked = 0
        for value, refs in carriers:
            for ref in refs:
                assert ref.artifact in docs, ref
                assert ref.sha256 == hashes[ref.artifact]
                for artifact, pointer in pointers((ref,)):
                    resolve_pointer(docs[artifact], pointer)
                if ref.derivation is None and value is not None:
                    assert resolve_pointer(docs[ref.artifact], ref.json_pointer) == value
                    checked += 1
            if value is not None and refs and {r.derivation for r in refs} & GOODPUT_DERIVATIONS:
                assert math.isclose(value, derived_goodput(docs, refs), rel_tol=1e-12)
                checked += 1
        assert checked > 0, name


def test_tg08_derived_aggregate_without_sum_cites_every_flow(fresh) -> None:
    inspection, run_view = load(fresh, "four_derived")
    docs = documents(inspection)
    aggregate = [
        s
        for s in goodput_series(run_view)
        if any(r.derivation == "AGGREGATE_DERIVED_FROM_FLOWS" for p in s.points for r in p.evidence)
    ]
    assert len(aggregate) == 1
    for point in aggregate[0].points:
        byte_pointers = [p for _, p in pointers(point.evidence) if p.endswith("/bytes")]
        assert len(byte_pointers) == 4
        assert math.isclose(point.value, derived_goodput(docs, point.evidence), rel_tol=1e-12)


def test_tg08_no_pointer_claims_a_computed_rate_is_raw(fresh) -> None:
    inspection, run_view = load(fresh, "captured_success")
    docs = documents(inspection)
    for value in all_display_values(run_view):
        for ref in value.evidence:
            if ref.json_pointer.endswith("/bits_per_second") and ref.derivation is None:
                assert resolve_pointer(docs[ref.artifact], ref.json_pointer) == value.value


# -------------------------------------------------- R-6 / R-11 / R-21 status views


def _tamper_checksum(run: Path) -> None:
    with (run / "client.stderr").open("ab") as handle:
        handle.write(b"x")


@pytest.mark.parametrize(
    ("mutate", "integrity_word"),
    [
        (_tamper_checksum, "integrity failed"),
        (lambda run: (run / ".run.lock").touch(), "unfinalized"),
    ],
    ids=["failed", "unfinalized"],
)
def test_r11_nonverified_views_show_no_derived_values(fresh, mutate, integrity_word) -> None:
    run = fresh("captured_success")
    mutate(run)
    inspection = core().load_run(run)
    run_view = view().build_view(inspection)
    assert integrity_word in run_view.integrity_text.casefold()
    assert "unverified" in run_view.traffic_text.casefold()
    assert "unverified" in run_view.eligibility_text.casefold()
    assert run_view.summary == run_view.flows == run_view.series == run_view.events == ()
    assert run_view.collectors == ()
    assert run_view.raw_artifacts == inspection.snapshot.artifacts


def test_r11_cancelled_view(fresh) -> None:
    import threading

    event = threading.Event()
    event.set()
    inspection = core().load_run(fresh("captured_success"), cancel=event)
    run_view = view().build_view(inspection)
    assert "cancelled" in run_view.integrity_text.casefold()
    assert run_view.summary == run_view.flows == run_view.series == ()


def test_r6_verified_views_use_the_snapshot_wording(fresh) -> None:
    _, run_view = load(fresh, "captured_success")
    assert "Verified snapshot" in run_view.integrity_text
    assert "current files" not in run_view.integrity_text.casefold()
    for name in ("no_server", "gap"):
        _, unreconciled = load(fresh, name)
        assert "Traffic result unverified" in unreconciled.traffic_text


def test_r11_verified_failed_run_without_report(fresh) -> None:
    _, run_view = load(fresh, "connection_timeout")
    assert run_view.series == ()
    goodput = find_summary(run_view, "goodput")
    assert goodput.value is None
    assert goodput.text.startswith("Unavailable: ")
    assert run_view.events  # logs remain inspectable


def test_r6_accepted_eligibility_is_never_rendered_as_accepted(fresh) -> None:
    run = fresh("captured_success")
    manifest = json.loads((run / "manifest.json").read_text())
    manifest["eligibility"] = {"status": "accepted", "reasons": []}
    (run / "manifest.json").write_text(json.dumps(manifest))
    inspection = core().load_run(run)
    text = view().build_view(inspection).eligibility_text
    assert not text.casefold().startswith("accepted")
    if str(inspection.integrity) == "verified":
        assert "Unsupported" in text
    else:
        assert "unverified" in text.casefold()


def test_events_are_the_verified_manifest_events(fresh) -> None:
    inspection, run_view = load(fresh, "four_omit")
    expected = documents(inspection)["manifest.json"]["events"]
    assert [dict(event) for event in run_view.events] == expected


# ------------------------------------------------------- R-9 sorting / R-10 filter


def test_r10_filter_is_literal_casefolded_substring(fresh) -> None:
    _, run_view = load(fresh, "four_omit")
    presenter = view()
    everything = presenter.filter_flows(run_view, "")
    assert everything == run_view.flows
    assert presenter.filter_flows(run_view, "   ") == run_view.flows
    one = presenter.filter_flows(run_view, " 10.99.0.10:41001 ")
    assert [row.socket_id for row in one] == [7]
    assert presenter.filter_flows(run_view, "10.99.0.20:5201") == run_view.flows
    assert presenter.filter_flows(run_view, ".*") == ()
    assert presenter.filter_flows(run_view, "[") == ()
    assert presenter.filter_flows(run_view, "no-such-thing") == ()


def test_r10_filter_matches_per_flow_quality_text_case_insensitively(fresh) -> None:
    inspection, run_view = load(fresh, "flow_flag")
    flagged = [
        flow.socket_id
        for flow in inspection.report.flows
        if "REPORTED_DURATION_UNAVAILABLE" in flow.sender.quality_flags
    ]
    assert flagged == [9]  # third flow (index 2) in the synthetic fixture
    rows = view().filter_flows(run_view, "reported_DURATION_unavailable")
    assert [row.socket_id for row in rows] == flagged


def _mean_rtt_label(run_view) -> str:
    labels = {
        value.label
        for row in run_view.flows
        for value in row.values
        if value.unit == "µs" and "mean" in value.label.casefold()
    }
    assert len(labels) == 1
    return labels.pop()


def test_r9_sorting_uses_original_values_and_socket_tiebreak(fresh) -> None:
    presenter = view()
    _, run_view = load(fresh, "four_omit")
    label = _mean_rtt_label(run_view)
    ascending = presenter.sort_flows(run_view.flows, label)
    assert [row.socket_id for row in ascending] == [5, 7, 9, 11]
    descending = presenter.sort_flows(run_view.flows, label, descending=True)
    assert [row.socket_id for row in descending] == [11, 9, 7, 5]
    with pytest.raises(ValueError):
        presenter.sort_flows(run_view.flows, "no such column")


def test_r9_unavailable_values_sort_last_in_both_directions(fresh) -> None:
    presenter = view()
    _, run_view = load(fresh, "four_derived")
    label = _mean_rtt_label(run_view)
    for descending in (False, True):
        rows = presenter.sort_flows(run_view.flows, label, descending=descending)
        assert [row.socket_id for row in rows] == [5, 7, 9, 11]


# ------------------------------------------------------------- presentation purity


def test_build_view_performs_no_io(fresh, monkeypatch: pytest.MonkeyPatch) -> None:
    inspection = core().load_run(fresh("four_omit"))
    presenter = view()

    def forbidden(*args, **kwargs):
        raise AssertionError("presentation must be pure")

    for target, attribute in [
        (builtins, "open"),
        (os, "open"),
        (os, "stat"),
        (os, "listdir"),
        (subprocess, "Popen"),
        (socket, "socket"),
    ]:
        monkeypatch.setattr(target, attribute, forbidden)
    run_view = presenter.build_view(inspection)
    presenter.filter_flows(run_view, "10.99")
    monkeypatch.undo()
    assert run_view.flows
