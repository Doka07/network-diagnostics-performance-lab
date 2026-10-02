"""Pure, Qt-free formatting and presentation of verified inspection snapshots."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace

from diaglab.inspection import ArtifactSnapshot, EvidenceReference, RunInspection
from diaglab.traffic.parser import _time_matches


@dataclass(frozen=True)
class DisplayValue:
    label: str
    text: str
    unit: str
    value: int | float | None
    evidence: tuple[EvidenceReference, ...] = ()

    unavailable_reason: str | None = None


@dataclass(frozen=True)
class FlowRow:
    socket_id: int
    values: tuple[DisplayValue, ...]
    search_text: str


@dataclass(frozen=True)
class ChartPoint:
    start_s: float
    end_s: float
    value: float | None
    omitted: bool
    break_before: bool
    evidence: tuple[EvidenceReference, ...] = ()
    raw_start_s: float | None = None
    raw_end_s: float | None = None


@dataclass(frozen=True)
class ChartSeries:
    label: str
    unit: str
    points: tuple[ChartPoint, ...]


@dataclass(frozen=True)
class RunView:
    integrity_text: str
    traffic_text: str
    eligibility_text: str
    summary: tuple[DisplayValue, ...] = ()
    flows: tuple[FlowRow, ...] = ()
    series: tuple[ChartSeries, ...] = ()
    events: tuple[Mapping, ...] = ()
    raw_artifacts: tuple[ArtifactSnapshot, ...] = ()
    collectors: tuple[DisplayValue, ...] = ()


UNITS = {"bps": "Mbit/s", "s": "s", "us": "µs", "bytes": "B", "count": "count"}


def format_value(value: int | float | None, unit: str, *, reason: str | None = None) -> str:
    if unit not in UNITS:
        raise ValueError("unknown source unit")
    if value is None:
        return f"Unavailable: {reason or 'NOT_RECORDED'}"
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("value must be finite and numeric")
    if unit in ("bytes", "count") and type(value) is not int:
        raise ValueError("bytes and counts require an integer")
    if unit == "bps":
        return f"{value / 1e6:.3f} Mbit/s"
    if unit == "s":
        return f"{value:.3f} s"
    if unit == "us":
        return f"{value:.3f} µs"
    return f"{value} B" if unit == "bytes" else str(value)


def _value(label, value, unit, evidence=(), reason=None):
    unavailable = (reason or "NOT_RECORDED") if value is None else None
    return DisplayValue(
        label,
        format_value(value, unit, reason=unavailable),
        UNITS[unit],
        value,
        tuple(evidence),
        unavailable,
    )


def build_view(inspection: RunInspection) -> RunView:
    raw = inspection.snapshot.artifacts
    if inspection.integrity != "verified":
        status = {
            "failed": "Integrity failed",
            "unfinalized": "Unfinalized",
            "cancelled": "Cancelled",
        }[inspection.integrity]
        return RunView(
            status, "Traffic state unverified", "Eligibility unverified", raw_artifacts=raw
        )
    report, verification = inspection.report, inspection.verification
    traffic = f"Traffic: {inspection.state}"
    if report is not None and not verification.result_verified:
        traffic = f"Traffic result unverified · {inspection.state}"
    if inspection.failure_reason:
        traffic += " · " + inspection.failure_reason
    eligibility = (
        "Eligibility: " + str(inspection.eligibility)
        if inspection.eligibility in ("pending", "rejected")
        else "Unsupported eligibility"
    )
    manifest = inspection.manifest
    collectors = tuple(
        DisplayValue(
            item["collector"],
            "Unavailable: NOT_IMPLEMENTED_PHASE2",
            "",
            None,
            (),
            "NOT_IMPLEMENTED_PHASE2",
        )
        for item in manifest.get("collector_coverage", ())
    )
    base = dict(
        integrity_text="Verified snapshot",
        traffic_text=traffic,
        eligibility_text=eligibility,
        raw_artifacts=raw,
        collectors=collectors,
        events=tuple(manifest.get("events", ())),
    )
    if report is None:
        return RunView(
            **base,
            summary=(_value("Receiver goodput", None, "bps", reason=inspection.failure_reason),),
        )
    evidence = inspection.evidence_map
    has_receiver = any(item.direction == "received" for item in report.intervals)
    summary = (
        _value(
            "Receiver goodput",
            report.receiver.computed_bps if has_receiver else None,
            "bps",
            evidence.get("goodput", ()) if has_receiver else (),
            "SERVER_OUTPUT_UNAVAILABLE",
        ),
        _value(
            "Endpoint byte residual",
            report.endpoint_byte_residual,
            "bytes",
            evidence.get("residual", ()),
        ),
        _value(
            "Sender retransmits",
            report.sender_retransmits,
            "count",
            evidence.get("retransmits", ()),
        ),
        DisplayValue(
            "Quality flags",
            ", ".join(report.quality_flags) or "No quality flags",
            "",
            len(report.quality_flags),
        ),
    )
    flows = []
    for flow in report.flows:
        values = tuple(
            _value(
                f"{label.title()} smoothed RTT",
                getattr(flow, f"{label}_rtt_us"),
                "us",
                evidence.get(("flow", flow.socket_id, label), ()),
                flow.rtt_unavailability_reason or "TCP_INFO_UNAVAILABLE",
            )
            for label in ("mean", "min", "max")
        )
        values += (
            _value(
                "Retransmits",
                flow.retransmits,
                "count",
                evidence.get(("flow", flow.socket_id, "retransmits"), ()),
            ),
        )
        flags = flow.sender.quality_flags + flow.receiver.quality_flags
        search = (
            f"{flow.socket_id} {flow.local_host}:{flow.local_port} → "
            f"{flow.remote_host}:{flow.remote_port} " + " ".join(flags)
        )
        flows.append(FlowRow(flow.socket_id, values, search))
    groups = {}
    for index, item in enumerate(report.intervals):
        received = item.direction == "received"
        stream = f"flow {item.socket_id}" if item.socket_id is not None else "aggregate"
        label = ("Receiver goodput" if received else "Sender throughput") + f" · {stream}"
        candidates = [
            (label, "Mbit/s", item.computed_bps, evidence.get(("interval", index, "rate"), ()))
        ]
        if not received and item.socket_id is not None:
            candidates.append(
                (
                    f"Smoothed RTT · {stream}",
                    "µs",
                    item.rtt_us,
                    evidence.get(("interval", index, "rtt"), ()),
                )
            )
        for label, unit, value, refs in candidates:
            points = groups.setdefault((label, unit), [])
            previous = points[-1] if points else None
            break_before = bool(
                previous
                and (
                    previous.omitted != item.omitted
                    or previous.value is None
                    or not _time_matches(item.start_s, previous.end_s)
                )
            )
            points.append(
                ChartPoint(
                    item.start_s,
                    item.end_s,
                    value,
                    item.omitted,
                    break_before,
                    refs,
                    item.start_s,
                    item.end_s,
                )
            )
    for points in groups.values():
        warm = [p for p in points if p.omitted]
        retained = [p for p in points if not p.omitted]
        if warm and retained:
            shift = min(0.0, min(p.start_s for p in retained) - max(p.end_s for p in warm))
            points[:] = [
                replace(p, start_s=p.start_s + shift, end_s=p.end_s + shift) if p.omitted else p
                for p in points
            ]
    series = tuple(
        ChartSeries(label, unit, tuple(points)) for (label, unit), points in groups.items()
    )
    return RunView(**base, summary=summary, flows=tuple(flows), series=series)


def filter_flows(view: RunView, query: str) -> tuple[FlowRow, ...]:
    token = query.strip().casefold()
    return tuple(row for row in view.flows if token in row.search_text.casefold())


def sort_flows(rows, column: str, *, descending=False) -> tuple[FlowRow, ...]:
    if not rows or any(column not in {value.label for value in row.values} for row in rows):
        raise ValueError("unknown flow column")

    def key(row):
        value = next(value.value for value in row.values if value.label == column)
        return (
            value is None,
            0 if value is None else (-value if descending else value),
            row.socket_id,
        )

    return tuple(sorted(rows, key=key))
