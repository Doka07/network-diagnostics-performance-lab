"""Explicit, offline export of minimized results from immutable run snapshots."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import asdict
from html import escape
from pathlib import Path

from diaglab.artifacts.store import ArtifactStore
from diaglab.exceptions import SafetyPreflightError
from diaglab.inspection import load_run
from diaglab.presentation import format_value

MAX_RUNS = 32
METRICS = {
    "receiver_goodput_bps": ("Receiver goodput", "bps"),
    "receiver_bytes": ("Receiver bytes", "bytes"),
    "receiver_duration_s": ("Retained duration", "s"),
    "sender_retransmits": ("Sender retransmits", "count"),
    "endpoint_byte_residual": ("Endpoint byte residual", "bytes"),
}
LIMITATIONS = (
    "Draft report. No performance claims have been accepted for publication.",
    "Synthetic runs are illustrations, and pilot runs are exploratory—not retained benchmarks.",
    "Integrity, traffic verification and evaluation eligibility are separate statuses.",
    "Runs are listed separately: no pooled averages, statistical comparison or causal diagnosis.",
    "Receiver goodput comes from the parser's non-omitted receiver result. Zero remains zero.",
    "Endpoint byte residual is not a packet-loss estimate. Retransmits are sender observations.",
    "Source hashes identify captured bytes; they do not authenticate experiment origin.",
    "Identifiers and raw logs are omitted. Review the report before sharing it.",
)


def _paths(paths: Sequence[Path]) -> tuple[Path, ...]:
    if isinstance(paths, (str, bytes, Path)) or not 1 <= len(paths) <= MAX_RUNS:
        raise SafetyPreflightError("results requires 1–32 explicit run directories")
    normalized = tuple(Path(os.path.abspath(path)) for path in paths)
    if len(set(normalized)) != len(normalized):
        raise SafetyPreflightError("duplicate run directories are not allowed")
    return normalized


def build_results(paths: Sequence[Path]) -> dict:
    """Load each source once, then keep only exportable fields and source digests."""
    paths = _paths(paths)
    rows = []
    seen_ids = set()
    for index, path in enumerate(paths, 1):
        inspection = load_run(path)
        intact = inspection.integrity == "verified"
        manifest = inspection.manifest if intact else None
        if manifest:
            run_id = manifest["run_id"]
            if run_id in seen_ids:
                raise SafetyPreflightError("repeated verified run IDs are not allowed")
            seen_ids.add(run_id)
        traffic = inspection.report
        result_verified = bool(inspection.verification and inspection.verification.result_verified)
        available = bool(
            intact
            and result_verified
            and traffic
            and traffic.receiver_source in ("embedded_server", "independent_server")
            and any(item.direction == "received" for item in traffic.intervals)
        )
        reason = (
            None
            if available
            else str(inspection.issues[0].code)
            if not intact
            else "NO_TRAFFIC_RESULT"
            if traffic is None
            else "RESULT_UNVERIFIED"
            if not result_verified
            else "RECEIVER_DATA_UNAVAILABLE"
        )
        metrics = dict.fromkeys(METRICS)
        if available:
            metrics.update(
                receiver_goodput_bps=traffic.receiver.computed_bps,
                receiver_bytes=traffic.receiver.bytes_count,
                receiver_duration_s=traffic.receiver.duration_s,
                sender_retransmits=traffic.sender_retransmits,
                endpoint_byte_residual=traffic.endpoint_byte_residual,
            )
        rows.append(
            {
                "label": f"Run {index}",
                "integrity": str(inspection.integrity),
                "state": inspection.state if intact else None,
                "evidence_kind": manifest["evidence_kind"] if manifest else None,
                "run_role": manifest["run_role"] if manifest else None,
                "eligibility": inspection.eligibility if intact else None,
                "result_verified": result_verified if intact else None,
                "issue_codes": [str(issue.code) for issue in inspection.issues],
                "quality_flags": list(traffic.quality_flags) if intact and traffic else [],
                "metrics": metrics,
                "unavailable_reason": reason,
                "source_digests": [
                    {"artifact": item.name, "size_bytes": item.size_bytes, "sha256": item.sha256}
                    for item in inspection.snapshot.artifacts
                    if item.data is not None and item.sha256 is not None
                ],
                "goodput_evidence": [
                    {**asdict(ref), "inputs": list(ref.inputs)}
                    for ref in inspection.evidence_map.get("goodput", ())
                ]
                if available
                else [],
            }
        )
    return {
        "schema_version": "1.0",
        "report_kind": "saved_run_results",
        "status": "draft",
        "performance_claims_accepted": False,
        "runs": rows,
        "limitations": list(LIMITATIONS),
    }


def render_html(report: dict) -> str:
    """Render a self-contained document; all source-derived strings are escaped."""
    cards = []
    for row in report["runs"]:

        def text(value):
            return escape(str(value)) if value is not None else "Unavailable"

        labels = " · ".join(text(row[key]) for key in ("evidence_kind", "run_role", "eligibility"))
        metrics = "".join(
            "<tr><th scope='row'>"
            + text(label)
            + "</th><td>"
            + text(format_value(row["metrics"][key], unit, reason=row["unavailable_reason"]))
            + "</td></tr>"
            for key, (label, unit) in METRICS.items()
        )
        codes = ", ".join(row["issue_codes"] + row["quality_flags"]) or "No recorded flags"
        provenance = escape(
            json.dumps(
                {
                    "source_digests": row["source_digests"],
                    "goodput_evidence": row["goodput_evidence"],
                },
                indent=2,
                allow_nan=False,
            )
        )
        synthetic = (
            "<p class='notice'>Synthetic illustration · not measured performance</p>"
            if row["evidence_kind"] == "synthetic"
            else ""
        )
        cards.append(
            "<section><div class='run-heading'><h2>" + text(row["label"]) + "</h2>"
            "<span>"
            + labels
            + "</span></div>"
            + synthetic
            + "<p>Integrity: <strong>"
            + text(row["integrity"])
            + "</strong> · Traffic: "
            + text(row["state"])
            + " · Traffic result verified: "
            + text(row["result_verified"])
            + "</p><table><tbody>"
            + metrics
            + "</tbody></table><p class='flags'>"
            + text(codes)
            + "</p><details><summary>Source digests and goodput evidence</summary><pre>"
            + provenance
            + "</pre></details></section>"
        )
    limits = "".join("<li>" + escape(item) + "</li>" for item in report["limitations"])
    return (
        """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy"
content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>DiagLab · saved-run results</title>
<style>
:root{color-scheme:light;font:16px system-ui,sans-serif;background:#edf2f6;color:#193047}
body{max-width:1050px;margin:48px auto;padding:0 24px}header{margin-bottom:32px}
h1{font-size:clamp(30px,5vw,48px);letter-spacing:-1px;margin:10px 0}h2{margin:0}
.eyebrow{color:#006b63;font-weight:700;letter-spacing:2px}p,li{line-height:1.6}
.notice{padding:14px 18px;background:#fff2d4;border-left:4px solid #a86a00;color:#654000}
section{background:white;border:1px solid #c8d4df;border-radius:12px;padding:24px;margin:20px 0}
.run-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}
.run-heading span,.flags{color:#4b6275}table{width:100%;border-collapse:collapse}
th,td{padding:12px 0;border-bottom:1px solid #dce4eb;text-align:left}td{text-align:right}
details{margin-top:18px}summary{cursor:pointer;color:#006b63}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}
footer{margin:36px 0} @media print{body{margin:0;background:white}section{break-inside:avoid}}
</style></head><body><header><div class="eyebrow">DIAGLAB / RESULTS</div>
<h1>Saved-run evidence, summarized.</h1>
<p>Offline report · captured snapshots · no cross-run statistical claims</p>
<p class="notice"><strong>Draft for review.</strong> No performance claims accepted.
Synthetic and pilot results are not retained benchmark evidence.</p></header>
"""
        + "\n".join(cards)
        + "<footer><h2>How to read this report</h2><ul>"
        + limits
        + "</ul></footer></body></html>\n"
    )


def export_results(paths: Sequence[Path], output: Path) -> Path:
    """Write a new report bundle outside every source tree, with checksums written last."""
    sources = _paths(paths)
    output = Path(os.path.abspath(output))
    for part in (output, *output.parents):
        if part.is_symlink():
            raise SafetyPreflightError("symlinked report destinations are not supported")
    if output.exists() and not output.is_dir():
        raise SafetyPreflightError("report destination must be an absent or empty directory")
    if output.is_dir() and any(output.iterdir()):
        raise SafetyPreflightError("report destination must be empty")
    for source in sources:
        if output.is_relative_to(source) or source.is_relative_to(output):
            raise SafetyPreflightError("report destination must be separate from every source tree")
        # Also reject aliases before any writes. ArtifactStore independently rejects symlinks.
        target, origin = output.resolve(), source.resolve()
        if target.is_relative_to(origin) or origin.is_relative_to(target):
            raise SafetyPreflightError("report destination aliases a source tree")
    report = build_results(sources)
    html = render_html(report).encode("utf-8")
    with ArtifactStore(output, create=True) as store:
        store.write_json("summary.json", report)
        store.write("report.html", html)
        checksums = {
            "schema_version": "1.0",
            "files": [store.digest(name) for name in ("report.html", "summary.json")],
        }
        # This bundle has its own two-file inventory, not the traffic-run schema.
        store.write_json("checksums.json", checksums)
    return output / "report.html"
