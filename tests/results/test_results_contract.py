"""RT-01–08: independent tests for the saved-run results report (docs/RESULTS_CONTRACTS.md).

Written from the contract before diaglab.results existed. Where the contract leaves a detail
open, the binding test assumption is recorded as RR-n in Claude's canonical review file and
named in the test; a disputed RR goes to Denis, and the test changes only if he rules so.

RR-1  Unverified integrity: state, evidence_kind, run_role, eligibility, result_verified are
      null and quality_flags is empty ("unknown unverified metadata is null").
RR-2  unavailable_reason is a code (UPPER_SNAKE, <=64 chars), never free text; for a
      non-verified row it is one of the row's issue_codes. Null iff goodput is numeric.
RR-3  report.html formats goodput with diaglab.presentation.format_value (one formatter).
RR-4  Duplicate inputs are detected at least after os.path.abspath normalization.
RR-5  A symlinked output directory is refused without writing through it.
RR-6  Zero --run arguments exit 1 or 2 (argparse may own it); nothing is created.
RR-7  source_digests holds exactly the snapshot's (name, size, sha256) triples, manifest
      included; key names and order are not pinned.
RR-8  All five metrics keys are always present (null when unavailable).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import stat
from html.parser import HTMLParser
from pathlib import Path

import pytest
from inspection.runs import edit_json, rehash, resolve_pointer, tree_state

from diaglab.inspection import load_run
from diaglab.presentation import format_value

from .conftest import cli, results, results_argv

ROOT_KEYS = {
    "schema_version",
    "report_kind",
    "status",
    "performance_claims_accepted",
    "runs",
    "limitations",
}
ROW_KEYS = {
    "label",
    "integrity",
    "state",
    "evidence_kind",
    "run_role",
    "eligibility",
    "result_verified",
    "issue_codes",
    "quality_flags",
    "metrics",
    "unavailable_reason",
    "source_digests",
    "goodput_evidence",
}
METRIC_KEYS = {
    "receiver_goodput_bps",
    "receiver_bytes",
    "receiver_duration_s",
    "sender_retransmits",
    "endpoint_byte_residual",
}
INTEGRITY = {"verified", "failed", "unfinalized", "cancelled"}
CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
COMPLETED = ("captured", "four_omit", "flow_flag", "zero")
UNAVAILABLE = (
    "no_server",
    "gap",
    "connection_timeout",
    "interrupted",
    "plan_synthetic_warmup",
    "phase1_manifest",
    "unfinalized",
    "tampered",
)


def build(paths: list[Path]) -> dict:
    return results().build_results(paths)


def row_for(path: Path) -> dict:
    report = build([path])
    assert len(report["runs"]) == 1
    return report["runs"][0]


def snapshot_bytes(inspection, name: str) -> bytes:
    return next(a.data for a in inspection.snapshot.artifacts if a.name == name)


def digest_triples(row: dict) -> set[tuple]:
    """RR-7: identify name/size/sha256 by value type, not by key name."""
    triples = set()
    for entry in row["source_digests"]:
        assert isinstance(entry, dict) and len(entry) == 3, entry
        values = list(entry.values())
        sha = [v for v in values if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)]
        size = [v for v in values if type(v) is int]
        name = [v for v in values if isinstance(v, str) and v not in sha]
        assert len(sha) == len(size) == len(name) == 1, entry
        triples.add((name[0], size[0], sha[0]))
    return triples


def export(paths: list[Path], output: Path, capsys) -> tuple[int, dict | None]:
    code, stdout, _ = cli(results_argv(paths, output), capsys)
    return code, (json.loads(stdout) if code == 0 else None)


# ------------------------------------------------------- RT-00 fixture sanity (core only)


def test_rt00_fixture_matrix_is_what_the_tests_assume(pristine) -> None:
    """Checked against the accepted core alone, so a wrong fixture cannot masquerade as
    an implementation defect (or hide one)."""
    for name in COMPLETED:
        inspection = load_run(pristine[name])
        assert str(inspection.integrity) == "verified", (name, inspection.issues)
        assert inspection.state == "completed", name
        assert inspection.verification.result_verified is True, name
        assert any(i.direction == "received" for i in inspection.report.intervals), name
    assert load_run(pristine["zero"]).report.receiver.computed_bps == 0
    assert load_run(pristine["flow_flag"]).report.quality_flags, "needs a parser flag"
    gap = load_run(pristine["gap"])  # the case the result_verified gate exists for
    assert any(i.direction == "received" for i in gap.report.intervals)
    assert gap.verification.result_verified is False
    for name, (integrity, state, code, verified) in EXPECTED.items():
        inspection = load_run(pristine[name])
        assert str(inspection.integrity) == integrity, (name, inspection.issues)
        if code:
            assert code in [str(issue.code) for issue in inspection.issues], name
        else:
            assert inspection.state == state, name
            assert inspection.verification.result_verified is verified, name


# ------------------------------------------------------------------ RT-01 value/source parity


@pytest.mark.parametrize("name", COMPLETED)
def test_rt01_metrics_are_copied_parser_values(fresh, name: str) -> None:
    run = fresh(name)
    inspection = load_run(run)
    report = inspection.report
    assert str(inspection.integrity) == "verified" and inspection.verification.result_verified
    row = row_for(run)
    assert set(row["metrics"]) == METRIC_KEYS  # RR-8
    expected = {
        "receiver_goodput_bps": report.receiver.computed_bps,
        "receiver_bytes": report.receiver.bytes_count,
        "receiver_duration_s": report.receiver.duration_s,
        "sender_retransmits": report.sender_retransmits,
        "endpoint_byte_residual": report.endpoint_byte_residual,
    }
    for key, value in expected.items():
        assert row["metrics"][key] == value, key  # exact: no rounding or recomputation
        assert type(row["metrics"][key]) is type(value), key  # ints stay ints, None stays None
    assert row["unavailable_reason"] is None
    assert row["quality_flags"] == list(report.quality_flags)


@pytest.mark.parametrize("name", ["captured", "four_omit"])
def test_rt01_goodput_evidence_resolves_in_the_source_bytes(fresh, name: str) -> None:
    run = fresh(name)
    inspection = load_run(run)
    row = row_for(run)
    core = [dataclasses.asdict(ref) for ref in inspection.evidence_map["goodput"]]
    normalized = [{**ref, "inputs": list(ref["inputs"])} for ref in row["goodput_evidence"]]
    assert normalized == [{**ref, "inputs": list(ref["inputs"])} for ref in core]
    assert row["goodput_evidence"], "core resolved goodput evidence for this run"
    client_bytes = snapshot_bytes(inspection, "client.json")
    client = json.loads(client_bytes)
    for ref in row["goodput_evidence"]:
        assert ref["artifact"] == "client.json"
        assert ref["sha256"] == hashlib.sha256(client_bytes).hexdigest()
        values = {p.rsplit("/", 1)[1]: resolve_pointer(client, p) for p in ref["inputs"]}
        assert values["bytes"] == row["metrics"]["receiver_bytes"]
        bps = values["bytes"] * 8 / (values["end"] - values["start"])
        assert row["metrics"]["receiver_goodput_bps"] == pytest.approx(bps, rel=1e-12)


def test_rt01_multiple_runs_are_reported_separately_never_pooled(fresh) -> None:
    runs = [fresh("captured"), fresh("four_omit"), fresh("zero")]
    report = build(runs)
    assert set(report) == ROOT_KEYS  # no pooled or aggregate figure at the root
    for run, row in zip(runs, report["runs"], strict=True):
        assert row["metrics"] == row_for(run)["metrics"]
        assert row["metrics"]["receiver_bytes"] == load_run(run).report.receiver.bytes_count


@pytest.mark.parametrize("name", [*COMPLETED, "no_server", "tampered", "plan_synthetic_warmup"])
def test_rt01_source_digests_are_the_snapshot_digests(fresh, name: str) -> None:
    run = fresh(name)
    inspection = load_run(run)
    row = row_for(run)
    captured = {
        (a.name, a.size_bytes, a.sha256)
        for a in inspection.snapshot.artifacts
        if a.data is not None
    }
    assert digest_triples(row) == captured  # RR-7
    assert any(name == "manifest.json" for name, _, _ in captured)
    for name_, size, sha in captured:
        data = (run / name_).read_bytes()
        assert (len(data), hashlib.sha256(data).hexdigest()) == (size, sha)


# ------------------------------------------------------------ RT-02 unavailable vs zero


def test_rt02_measured_zero_goodput_is_numeric_zero(fresh) -> None:
    row = row_for(fresh("zero"))
    assert row["integrity"] == "verified" and row["result_verified"] is True
    assert row["metrics"]["receiver_goodput_bps"] == 0
    assert row["metrics"]["receiver_goodput_bps"] is not None
    assert row["metrics"]["receiver_bytes"] == 0
    assert row["unavailable_reason"] is None


@pytest.mark.parametrize("name", UNAVAILABLE)
def test_rt02_unavailable_rows_are_all_null_with_a_code(fresh, name: str) -> None:
    row = row_for(fresh(name))
    assert set(row["metrics"]) == METRIC_KEYS  # RR-8
    assert all(value is None for value in row["metrics"].values()), row["metrics"]
    assert row["goodput_evidence"] == []
    reason = row["unavailable_reason"]
    assert isinstance(reason, str) and CODE.fullmatch(reason), reason  # RR-2
    if row["integrity"] != "verified":
        assert reason in row["issue_codes"]


def test_rt02_html_distinguishes_zero_from_unavailable(fresh) -> None:
    """RR-3: one formatter; a zero is shown as a value, a missing value never as zero."""
    zero_html = results().render_html(build([fresh("zero")]))
    assert format_value(0.0, "bps") in zero_html
    missing_html = results().render_html(build([fresh("connection_timeout")]))
    assert "Unavailable" in missing_html
    assert format_value(0.0, "bps") not in missing_html
    completed = build([fresh("captured")])
    value = completed["runs"][0]["metrics"]["receiver_goodput_bps"]
    assert format_value(value, "bps") in results().render_html(completed)


# --------------------------------------------------- RT-03 invalid / missing / failed inputs

EXPECTED = {
    # name: (integrity, state, required issue code, result_verified)
    "connection_timeout": ("verified", "failed", None, False),
    "no_server": ("verified", "failed", None, False),
    "gap": ("verified", "failed", None, False),
    "interrupted": ("verified", "interrupted", None, False),
    "plan_synthetic_warmup": ("verified", "planned", None, False),
    "phase1_manifest": ("verified", "planned", None, False),
    "unfinalized": ("unfinalized", None, "RUN_UNFINALIZED", None),
    "tampered": ("failed", None, "CHECKSUM_MISMATCH", None),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_rt03_each_input_kind_becomes_an_honest_row(fresh, name: str) -> None:
    integrity, state, code, verified = EXPECTED[name]
    row = row_for(fresh(name))
    assert set(row) == ROW_KEYS
    assert row["label"] == "Run 1"
    assert row["integrity"] == integrity
    assert row["state"] == state
    assert row["result_verified"] is verified
    if code:
        assert code in row["issue_codes"]
        # RR-1: unverified manifest metadata is not exported as fact
        for key in ("state", "evidence_kind", "run_role", "eligibility", "result_verified"):
            assert row[key] is None, key
        assert row["quality_flags"] == []
    else:
        assert row["issue_codes"] == []
        assert row["eligibility"] in ("pending", "rejected")


def test_rt03_unverified_traffic_keeps_its_parser_flags(fresh) -> None:
    run = fresh("no_server")
    row = row_for(run)
    assert row["quality_flags"] == list(load_run(run).report.quality_flags)
    assert "SERVER_OUTPUT_UNAVAILABLE" in row["quality_flags"]


def test_rt03_missing_inputs_are_rows_not_dropped(fresh, tmp_path: Path, out, capsys) -> None:
    present = fresh("captured")
    missing = tmp_path / "does-not-exist"
    code, announced = export([missing, present], out, capsys)
    assert code == 0
    assert announced["run_count"] == 2
    rows = json.loads((out / "summary.json").read_text())["runs"]
    assert [r["label"] for r in rows] == ["Run 1", "Run 2"]
    assert "INPUT_MISSING" in rows[0]["issue_codes"]
    assert rows[0]["integrity"] != "verified"
    assert all(v is None for v in rows[0]["metrics"].values())
    assert rows[1]["integrity"] == "verified"


def test_rt03_mixed_inputs_export_with_exit_0(fresh, out, capsys) -> None:
    names = ["captured", "tampered", "unfinalized", "plan_synthetic_warmup", "interrupted"]
    runs = [fresh(n) for n in names]
    code, announced = export(runs, out, capsys)
    assert code == 0 and announced["run_count"] == len(names)
    rows = json.loads((out / "summary.json").read_text())["runs"]
    assert [r["integrity"] for r in rows] == [
        "verified",
        "failed",
        "unfinalized",
        "verified",
        "verified",
    ]
    assert all(r["integrity"] in INTEGRITY for r in rows)


# ------------------------------------------------------------------- RT-04 evidence classes


@pytest.mark.parametrize(
    ("name", "kind", "role"),
    [
        ("plan_synthetic_warmup", "synthetic", "warmup"),
        ("plan_measured_pilot", "measured", "pilot"),
        ("captured", "pilot", "pilot"),
    ],
)
def test_rt04_evidence_kind_and_role_are_copied(fresh, name, kind, role) -> None:
    run = fresh(name)
    manifest = json.loads((run / "manifest.json").read_text())
    assert (manifest["evidence_kind"], manifest["run_role"]) == (kind, role)  # fixture sanity
    row = row_for(run)
    assert (row["evidence_kind"], row["run_role"]) == (kind, role)
    html = results().render_html(build([run]))
    assert kind in html and role in html


def test_rt04_root_never_claims_acceptance(fresh) -> None:
    report = build([fresh("captured"), fresh("plan_measured_pilot")])
    assert set(report) == ROOT_KEYS
    assert report["schema_version"] == "1.0"
    assert report["report_kind"] == "saved_run_results"
    assert report["status"] == "draft"
    assert report["performance_claims_accepted"] is False
    assert report["limitations"] and all(isinstance(x, str) and x for x in report["limitations"])


def test_rt04_forged_acceptance_is_never_upgraded(fresh) -> None:
    """Manifest eligibility is not checksummed; a hand-edited 'accepted' must not surface."""
    run = fresh("captured")
    edit_json(run, "manifest.json", lambda m: m["eligibility"].update(status="accepted"))
    row = row_for(run)
    assert row["eligibility"] != "accepted"
    assert row["eligibility"] in (None, "pending", "rejected")
    assert "accepted" not in json.dumps(row["eligibility"])


# --------------------------------------------------------------- RT-05 no source mutation


def test_rt05_export_never_mutates_any_input(fresh, tmp_path: Path, out, capsys) -> None:
    names = ["captured", "four_omit", "unfinalized", "tampered", "no_server", "phase1_manifest"]
    runs = [fresh(n) for n in names]
    before = {run: tree_state(run) for run in runs}
    code, _ = export(runs, out, capsys)
    assert code == 0
    for run in runs:
        assert tree_state(run) == before[run], run.name
    assert (runs[2] / ".run.lock").exists()  # the viewer never clears another run's lock


def test_rt05_each_input_is_captured_exactly_once(fresh, monkeypatch) -> None:
    import diaglab.inspection as core

    module = results()
    calls: list[Path] = []
    original = core.capture_run

    def counting(path, *args, **kwargs):
        calls.append(Path(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(core, "capture_run", counting)
    if getattr(module, "capture_run", None) is original:
        monkeypatch.setattr(module, "capture_run", counting)
    runs = [fresh("captured"), fresh("no_server"), fresh("tampered")]
    module.build_results(runs)
    assert sorted(map(str, calls)) == sorted(map(str, runs))


# --------------------------------------------- RT-06 output safety, duplicates and bounds


def assert_refused(code: int, output: Path, existed: bool) -> None:
    assert code == 1, code
    if not existed:
        assert not output.exists() and not output.is_symlink()


def test_rt06_bundle_has_exactly_three_private_files(fresh, out, capsys) -> None:
    code, _ = export([fresh("captured")], out, capsys)
    assert code == 0
    assert sorted(os.listdir(out)) == ["checksums.json", "report.html", "summary.json"]
    for name in os.listdir(out):
        assert stat.S_IMODE((out / name).stat().st_mode) == 0o600, name


def test_rt06_empty_existing_output_is_accepted(fresh, out, capsys) -> None:
    out.mkdir(parents=True)
    code, _ = export([fresh("captured")], out, capsys)
    assert code == 0 and (out / "checksums.json").exists()


def test_rt06_nonempty_output_is_refused_untouched(fresh, out, capsys) -> None:
    out.mkdir(parents=True)
    (out / "keep.txt").write_text("owner data")
    before = tree_state(out)
    code, _ = export([fresh("captured")], out, capsys)
    assert_refused(code, out, existed=True)
    assert tree_state(out) == before


@pytest.mark.parametrize("where", ["equal", "inside", "contains"])
def test_rt06_output_overlapping_an_input_is_refused(fresh, capsys, where: str) -> None:
    run = fresh("captured")
    other = fresh("four_omit")
    output = {"equal": run, "inside": run / "report", "contains": run.parent}[where]
    existed = output.exists()
    states = {r: tree_state(r) for r in (run, other)}
    code, _ = export([other, run], output, capsys)
    assert_refused(code, output, existed)
    for r, state in states.items():
        assert tree_state(r) == state


def test_rt06_symlinked_output_is_not_followed(fresh, tmp_path: Path, capsys) -> None:
    """RR-5."""
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    code, _ = export([fresh("captured")], link, capsys)
    assert code != 0
    assert os.listdir(target) == []


@pytest.mark.parametrize("kind", ["captured", "tampered", "missing"])
@pytest.mark.parametrize("form", ["trailing_slash", "dotdot"])
def test_rt06_duplicate_normalized_paths_are_refused(
    fresh, tmp_path: Path, out, capsys, form: str, kind: str
) -> None:
    """RR-4. Tampered and missing inputs have no verified run ID, so only the path check
    can refuse them; a verified duplicate would also trip the run-ID check."""
    run = tmp_path / "inputs" / "absent-run" if kind == "missing" else fresh(kind)
    alias = {
        "trailing_slash": str(run) + os.sep,
        "dotdot": str(run.parent / "x" / ".." / run.name),
    }[form]
    # Raw strings: Path() would already strip the trailing slash being tested.
    argv = ["results", "--run", str(run), "--run", alias, "--output", str(out)]
    code, _, _ = cli(argv, capsys)
    assert_refused(code, out, existed=False)
    with pytest.raises(Exception):  # noqa: B017 - the contract names no exception type
        build([run, Path(alias)])


def test_rt06_repeated_verified_run_id_is_refused(fresh, out, capsys) -> None:
    first, copy = fresh("captured"), fresh("captured")
    assert first != copy
    code, _ = export([first, copy], out, capsys)
    assert_refused(code, out, existed=False)


def test_rt06_count_bounds(tmp_path: Path, out, capsys) -> None:
    missing = [tmp_path / "absent" / f"run-{i:02d}" for i in range(33)]
    code, _ = export(missing, out, capsys)
    assert_refused(code, out, existed=False)
    code, announced = export(missing[:32], out, capsys)
    assert code == 0 and announced["run_count"] == 32
    rows = json.loads((out / "summary.json").read_text())["runs"]
    assert [r["label"] for r in rows] == [f"Run {i}" for i in range(1, 33)]
    assert all("INPUT_MISSING" in r["issue_codes"] for r in rows)


def test_rt06_zero_runs_are_refused(out, capsys) -> None:
    """RR-6."""
    code, _, _ = cli(["results", "--output", str(out)], capsys)
    assert code in (1, 2)
    assert not out.exists()


def test_rt06_labels_follow_input_order(fresh) -> None:
    a, b = fresh("captured"), fresh("zero")
    forward = build([a, b])["runs"]
    reverse = build([b, a])["runs"]
    assert [r["label"] for r in forward] == [r["label"] for r in reverse] == ["Run 1", "Run 2"]
    assert forward[0]["metrics"] == reverse[1]["metrics"]
    assert forward[1]["metrics"] == reverse[0]["metrics"]


# --------------------------------------------------------------- RT-07 escaping and privacy

MARKUP = '<a href="https://example.invalid/x">PRIVATE-REASON</a><!-- hidden -->'
STDERR_MARKER = b"<script>alert('STDERR-PRIVATE-MARKER')</script>"


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def private_strings(run: Path) -> list[str]:
    manifest = json.loads((run / "manifest.json").read_text())
    values = [str(run), str(run.resolve()), manifest["run_id"], manifest["campaign_id"]]
    command_path = run / "command.json"
    if command_path.exists():
        command = json.loads(command_path.read_text())
        values += [command["argv"][0], "--get-server-output", "--connect-timeout"]
        if command.get("source_ip"):
            values.append(command["source_ip"])
    client = run / "client.json"
    if client.exists():
        for row in json.loads(client.read_text()).get("start", {}).get("connected", []):
            values += [row["local_host"], row["remote_host"]]
            values += [f"{row['local_host']}:{row['local_port']}", f":{row['remote_port']}"]
    events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
    # Event content, not names: names such as RUN_FAILED are legitimate code vocabulary.
    values += [event["timestamp_utc"] for event in events if "timestamp_utc" in event]
    values += [str(event["monotonic_ns"]) for event in events if "monotonic_ns" in event]
    values += ['"server_output_json"', '"connected"', '"test_start"']  # raw JSON keys
    return [v for v in values if v]


def test_rt07_no_private_or_raw_material_is_exported(fresh, out, capsys) -> None:
    clean = fresh("four_omit")
    stderr = fresh("captured")
    with (stderr / "client.stderr").open("ab") as handle:
        handle.write(STDERR_MARKER)
    rehash(stderr)
    reason = fresh("connection_timeout")
    edit_json(reason, "command.json", lambda c: c.update(failure_reason=MARKUP))
    rehash(reason)
    runs = [clean, stderr, reason]
    assert all(str(load_run(r).integrity) == "verified" for r in runs)  # fixture sanity
    code, _ = export(runs, out, capsys)
    assert code == 0
    exported = (out / "summary.json").read_text() + (out / "report.html").read_text()
    forbidden = [str(out), "PRIVATE-REASON", "STDERR-PRIVATE-MARKER", "example.invalid"]
    for run in runs:
        forbidden += private_strings(run)
    leaks = sorted({value for value in forbidden if value in exported})
    assert not leaks, leaks


def _walk(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _walk(item, (*path, key))
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item, (*path, "[]"))
    else:
        yield path, value


def test_rt07_summary_is_a_closed_structure(fresh) -> None:
    report = build([fresh("captured"), fresh("tampered"), fresh("connection_timeout")])
    assert set(report) == ROOT_KEYS
    fields = {f.name for f in dataclasses.fields(type(load_run(fresh("captured")).evidence[0]))}
    for row in report["runs"]:
        assert set(row) == ROW_KEYS
        assert set(row["metrics"]) == METRIC_KEYS
        for ref in row["goodput_evidence"]:
            assert set(ref) == fields
        assert all(isinstance(code, str) and CODE.fullmatch(code) for code in row["issue_codes"])
    for path, value in _walk(report):
        if isinstance(value, str) and path[:2] == ("runs", "[]"):
            allowed = path[2] in {
                "label",
                "integrity",
                "state",
                "evidence_kind",
                "run_role",
                "eligibility",
                "issue_codes",
                "quality_flags",
                "unavailable_reason",
                "source_digests",
                "goodput_evidence",
            }
            assert allowed, path
            assert len(value) <= 256, path


def test_rt07_html_is_self_contained_and_inert(fresh) -> None:
    html = results().render_html(build([fresh("captured"), fresh("tampered")]))
    parser = _Tags()
    parser.feed(html)
    banned = {"script", "iframe", "object", "embed", "link", "img", "base", "form", "frame"}
    for tag, attrs in parser.tags:
        assert tag not in banned, tag
        for name, value in attrs.items():
            assert not name.startswith("on"), (tag, name)
            assert not re.match(r"\s*(https?:|//|javascript:|data:)", value or "", re.I), (
                tag,
                name,
                value,
            )
        if tag == "meta":
            assert attrs.get("http-equiv", "").lower() != "refresh"
    lowered = html.lower()
    for needle in ("@import", "url(", "http://", "https://", "@font-face"):
        assert needle not in lowered, needle


def test_rt07_render_html_escapes_every_string(fresh) -> None:
    report = build([fresh("flow_flag")])
    payload = "<b>x</b>&\"'"
    report["runs"][0]["label"] = "Run 1 " + payload
    report["runs"][0]["quality_flags"] = [*report["runs"][0]["quality_flags"], payload]
    report["limitations"] = [*report["limitations"], payload]
    html = results().render_html(report)
    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;&amp;" in html


# ------------------------------------------------------------------- RT-08 CLI and checksums


def test_rt08_cli_announces_the_bundle(fresh, out, capsys) -> None:
    runs = [fresh("captured"), fresh("zero")]
    code, announced = export(runs, out, capsys)
    assert code == 0
    assert announced["performance_claims_accepted"] is False
    assert announced["run_count"] == 2
    report = Path(announced["report"])
    assert report.exists()
    assert report.resolve() == out.resolve() or out.resolve() in report.resolve().parents


def test_rt08_summary_file_equals_build_results(fresh, out, capsys) -> None:
    runs = [fresh("captured"), fresh("four_omit"), fresh("tampered"), fresh("zero")]
    code, _ = export(runs, out, capsys)
    assert code == 0
    assert json.loads((out / "summary.json").read_text()) == build(runs)  # exact floats


def test_rt08_checksums_cover_the_bundle(fresh, out, capsys) -> None:
    code, _ = export([fresh("captured")], out, capsys)
    assert code == 0
    listed = json.loads((out / "checksums.json").read_text())
    text = json.dumps(listed)
    for name in ("summary.json", "report.html"):
        data = (out / name).read_bytes()
        assert name in text
        assert hashlib.sha256(data).hexdigest() in text, name
    assert hashlib.sha256((out / "checksums.json").read_bytes()).hexdigest() not in text


def test_rt08_export_results_returns_a_path_in_the_bundle(fresh, out) -> None:
    path = results().export_results([fresh("captured")], out)
    assert isinstance(path, Path)
    assert path.resolve() == out.resolve() or out.resolve() in path.resolve().parents


def test_rt08_usage_errors_exit_2(out, capsys) -> None:
    code, _, _ = cli(["results", "--run", "x", "--output", str(out), "--bogus"], capsys)
    assert code == 2
    assert not out.exists()


def test_rt08_write_failure_exits_3_without_final_checksums(fresh, out, capsys, monkeypatch):
    from diaglab.artifacts import store as store_module

    def failing(original):
        def wrapper(self, name, *args, **kwargs):
            if name == "report.html":
                raise OSError("injected write failure")
            return original(self, name, *args, **kwargs)

        return wrapper

    for method in ("write", "write_json", "open_new"):
        original = getattr(store_module.ArtifactStore, method)
        monkeypatch.setattr(store_module.ArtifactStore, method, failing(original))
    run = fresh("captured")
    before = tree_state(run)
    code, _, _ = cli(results_argv([run], out), capsys)
    assert code == 3
    assert not (out / "checksums.json").exists()
    assert tree_state(run) == before
    monkeypatch.undo()
    code, _, _ = cli(results_argv([run], out), capsys)  # never overwrite a partial bundle
    if out.exists() and os.listdir(out):
        assert code == 1
