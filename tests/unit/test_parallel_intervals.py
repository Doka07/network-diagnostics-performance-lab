"""PX-01–10: reported versus derived parallel interval aggregates (docs/PHASE2_CONTRACTS.md,
"For a supplied interval `sum` ..."), written from the contract before reading the
2026-10-03 parser change.

Real iperf 3.16 four-stream output samples each flow's interval boundary separately (the
first epoch's ends differed by 2–3 µs) while the supplied `sum` carries the first
stream's timestamps. The contract: keep every flow's actual window and the supplied
aggregate's window; aggregate bytes must equal the flow bytes exactly; the aggregate
window must match the first flow; differing flow windows must overlap positively and add
PARALLEL_INTERVAL_WINDOWS_DIFFER; nothing is silently aligned. Without a supplied sum,
differing windows still fail with WINDOW_MISMATCH. Serialization tolerances are unchanged.

Binding test assumptions (PR-n in Claude's canonical review):
PR-1  A rejection is a TrafficExecutionError; WINDOW_MISMATCH appears in its message or
      reason_code (the contract names the condition, not the field that carries it).
PR-2  PARALLEL_INTERVAL_WINDOWS_DIFFER appears in report.quality_flags or an endpoint's
      quality_flags. Differences inside the unchanged 1e-6 s tolerance are not "differing".
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from inspection.runs import synthetic_document

from diaglab.exceptions import TrafficExecutionError
from diaglab.traffic.parser import parse_iperf3

STREAMS = 4
SKEW = (0.0, 2.0e-6, 3.0e-6, 2.5e-6)  # first flow unchanged, like the real pilot
FLAG = "PARALLEL_INTERVAL_WINDOWS_DIFFER"


def document(*, with_sum: bool = True) -> dict:
    return synthetic_document(streams=STREAMS, retained=3, with_sum=with_sum)


def sides(doc: dict, side: str) -> list[dict]:
    return doc["intervals"] if side == "client" else doc["server_output_json"]["intervals"]


def _rate(row: dict) -> None:
    row["seconds"] = row["end"] - row["start"]
    row["bits_per_second"] = row["bytes"] * 8 / row["seconds"]


def skew_boundary(doc: dict, side: str, epoch: int = 0, deltas=SKEW) -> dict:
    """Move each flow's end of `epoch` (and the next epoch's start) by its own delta,
    keeping bytes: independently sampled flow clocks, continuous within each flow."""
    epochs = sides(doc, side)
    for index, delta in enumerate(deltas):
        epochs[epoch]["streams"][index]["end"] += delta
        _rate(epochs[epoch]["streams"][index])
        if epoch + 1 < len(epochs):
            epochs[epoch + 1]["streams"][index]["start"] += delta
            _rate(epochs[epoch + 1]["streams"][index])
    return doc


def parse(doc: dict):
    return parse_iperf3(json.dumps(doc), expected_streams=STREAMS, omit_s=0.0)


def flags(report) -> set[str]:
    found = set(report.quality_flags)
    for endpoint in (report.sender, report.receiver):
        found |= set(endpoint.quality_flags)
    return found


def intervals(report, direction: str, socket_id):
    return [
        item
        for item in report.intervals
        if str(item.direction) == direction and item.socket_id == socket_id
    ]


def assert_rejected(doc: dict, needle: str | None = None) -> TrafficExecutionError:
    with pytest.raises(TrafficExecutionError) as excinfo:
        parse(doc)
    if needle:
        text = f"{excinfo.value} {excinfo.value.reason_code}"
        assert needle in text, text
    return excinfo.value


SIDE = pytest.mark.parametrize(("side", "direction"), [("client", "sent"), ("server", "received")])


# ------------------------------------------------- PX-01 supplied aggregate, skewed flows


@SIDE
def test_px01_supplied_sum_with_independently_sampled_flows_is_accepted_and_flagged(
    side, direction
) -> None:
    report = parse(skew_boundary(document(), side))
    assert FLAG in flags(report)  # PR-2


@SIDE
def test_px02_each_flow_keeps_its_actual_window(side, direction) -> None:
    doc = skew_boundary(document(), side)
    raw = sides(doc, side)
    report = parse(doc)
    ids = [row["socket"] for row in raw[0]["streams"]]
    connected = {row["socket"] for row in doc["start"]["connected"]}
    for index, socket_id in enumerate(ids):
        # client IDs are the reported flow IDs; server IDs are remapped to client flows
        flow_id = (
            socket_id if socket_id in connected else doc["start"]["connected"][index]["socket"]
        )
        series = intervals(report, direction, flow_id)
        assert [(i.start_s, i.end_s) for i in series[:2]] == [
            (raw[0]["streams"][index]["start"], raw[0]["streams"][index]["end"]),
            (raw[1]["streams"][index]["start"], raw[1]["streams"][index]["end"]),
        ], (side, index)  # exact: not rounded, not aligned to the sum


@SIDE
def test_px03_aggregate_keeps_the_supplied_window_and_exact_bytes(side, direction) -> None:
    doc = skew_boundary(document(), side)
    supplied = sides(doc, side)[0]["sum"]
    report = parse(doc)
    aggregate = intervals(report, direction, None)[0]
    assert (aggregate.start_s, aggregate.end_s) == (supplied["start"], supplied["end"])
    first = sides(doc, side)[0]["streams"][0]
    assert (aggregate.start_s, aggregate.end_s) == (first["start"], first["end"])
    assert aggregate.bytes_count == supplied["bytes"]
    assert aggregate.bytes_count == sum(row["bytes"] for row in sides(doc, side)[0]["streams"])
    expected = supplied["bytes"] * 8 / (supplied["end"] - supplied["start"])
    assert math.isclose(aggregate.computed_bps, expected, rel_tol=1e-12)  # sum's own window


def test_px04_aligned_flows_are_not_flagged() -> None:
    assert FLAG not in flags(parse(document()))


def test_px05_skew_inside_the_unchanged_tolerance_is_not_differing() -> None:
    report = parse(skew_boundary(document(), "client", deltas=(0.0, 5e-7, 4e-7, 3e-7)))
    assert FLAG not in flags(report)  # PR-2: tolerance unchanged


# ------------------------------------------------------ PX-06 supplied aggregate rejected


@SIDE
def test_px06_supplied_sum_bytes_must_match_flows_exactly(side, direction) -> None:
    doc = skew_boundary(document(), side)
    sides(doc, side)[0]["sum"]["bytes"] += 1
    _rate(sides(doc, side)[0]["sum"])
    assert_rejected(doc)


@SIDE
def test_px07_supplied_window_must_match_the_first_flow(side, direction) -> None:
    doc = skew_boundary(document(), side)
    epochs = sides(doc, side)
    # Move the sum's boundary to flow 2's clock, keeping the aggregate series continuous,
    # so only the "aggregate window matches the first flow" rule can reject it.
    epochs[0]["sum"]["end"] += 3e-6
    epochs[1]["sum"]["start"] += 3e-6
    _rate(epochs[0]["sum"])
    _rate(epochs[1]["sum"])
    assert_rejected(doc)


@SIDE
def test_px08_flow_windows_without_positive_overlap_are_rejected(side, direction) -> None:
    """Flow 3 runs a whole second later (touching, zero overlap with the others)."""
    doc = document()
    for epoch in sides(doc, side):
        row = epoch["streams"][3]
        row["start"] += 1.0
        row["end"] += 1.0
    assert_rejected(doc)


# ------------------------------------------------------- PX-09 derived aggregate unchanged


def test_px09_without_a_supplied_sum_differing_windows_are_window_mismatch() -> None:
    doc = skew_boundary(document(with_sum=False), "client")
    assert_rejected(doc, "WINDOW_MISMATCH")  # PR-1


def test_px09_without_a_supplied_sum_aligned_flows_still_derive() -> None:
    report = parse(document(with_sum=False))
    assert FLAG not in flags(report)
    aggregate = intervals(report, "sent", None)
    assert aggregate, "aggregate intervals derived from aligned flows"


# --------------------------------------------- PX-10 end-to-end: runner, verify, viewer


def test_px10_skewed_four_stream_run_verifies_and_every_pointer_resolves(
    tmp_path, base_config
) -> None:
    """The real failure mode end to end: the accepted runner completes, CLI verify and the
    viewer agree, evidence resolves, and per-flow series are not broken by the skew."""
    from inspection.runs import RunBuilder, resolve_pointer

    from diaglab.inspection import load_run
    from diaglab.presentation import build_view
    from diaglab.run import verify_run

    doc = skew_boundary(skew_boundary(document(), "client"), "server")
    run = RunBuilder(tmp_path, base_config)._execute(
        "skew", json.dumps(doc), duration_s=3, streams=STREAMS
    )
    manifest = json.loads((run / "manifest.json").read_text())
    assert manifest["state"] == "completed", manifest["eligibility"]
    assert verify_run(run).result_verified is True
    inspection = load_run(run)
    assert str(inspection.integrity) == "verified", inspection.issues
    assert FLAG in flags(inspection.report)
    client = json.loads(
        next(a.data for a in inspection.snapshot.artifacts if a.name == "client.json")
    )
    assert inspection.evidence, "provenance resolved for the skewed run"
    for ref in inspection.evidence:
        for pointer in (ref.json_pointer, *ref.inputs):
            if pointer:
                resolve_pointer(client, pointer)  # raises if it does not resolve
    for series in build_view(inspection).series:
        if "aggregate" not in series.label:
            assert not any(p.break_before for p in series.points), series.label


@pytest.fixture
def base_config() -> dict:
    import yaml

    path = Path(__file__).resolve().parents[2] / "configs" / "baseline.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))
