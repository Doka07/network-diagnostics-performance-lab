# GUI steps 1–2 contracts — implementation review

Owner accepted Phase 2 software and authorized a visual mockup and offline viewer.
Claude retains existing independent test ownership and code review. Gemini provides a
second independent methodology and GUI review. These concrete
interfaces incorporate Claude's R-1–R-26 resolutions below. Implementation and independent
tests are present; final implementation review remains pending.

The inspected result additionally exposes `failure_reason: str | None` from the verified
command record. Failed/interrupted traffic reasons appear in the main status; when no
report exists they also explain unavailable goodput. Raw unverified reasons are not promoted
to verified status. Flow cells may abbreviate missing values to "Unavailable" when their
full reason remains available in tooltips/details, preserving readable flow identities.

## Scope and platform

Linux/POSIX controller only; Windows returns PLATFORM_UNSUPPORTED without opening files.
The viewer opens one explicitly selected run directory at a time; it does not recursively
scan folders. No Start/Stop/Plan control, run execution, packet capture, SSH, sockets,
subprocesses, exports or evidence mutation exists in steps 1–2.
Future live controls require a separate worker/shutdown contract. Closing this viewer
cancels only read-only loading; it does not manage an external traffic run.

## Shared core: diaglab.inspection

No Qt imports. Frozen dataclasses and tuples; immutable bytes and detached read-only
mappings. Enums are StrEnum. All reason/path attributes are structured, never inferred
by parsing exception text. Implemented signatures:

```python
def capture_run(
    path: Path, *, cancel: Event | None = None, progress: Callable[[int, int], None] | None = None
) -> RunSnapshot: ...
def inspect_snapshot(snapshot: RunSnapshot) -> RunInspection: ...
def load_run(
    path: Path,
    *,
    cancel: Event | None = None,
    progress: Callable[[int, int], None] | None = None,
    include_evidence: bool = True,
) -> RunInspection: ...
```

RunSnapshot fields: root (Path), artifacts (tuple[ArtifactSnapshot, ...]), entry_names
(tuple[str, ...]), issues (tuple[InspectionIssue, ...]), finalized (bool).
ArtifactSnapshot: name (str), data (bytes | None), sha256 (str | None), size_bytes
(int | None), issue (InspectionIssue | None). Never retain open descriptors.
InspectionIssue: code (InspectionCode), path (str | None), message (str, <=512 characters).
Paths are flat relative artifact names, or null for root/general errors.

RunInspection fields: snapshot (RunSnapshot), integrity (IntegrityStatus), issues
(tuple[InspectionIssue, ...]), verification (VerificationResult | None), state
(str | None), eligibility (str | None), report (Iperf3Report | None), manifest
(Mapping | None), evidence (tuple[EvidenceReference, ...]).
IntegrityStatus: verified, failed, unfinalized, cancelled.
State: planned, running, completed, failed, interrupted; null if no validated manifest.
Eligibility: pending/rejected from a validated manifest; other values are unsupported
for this viewer release and never rendered as accepted. On failed integrity state and
eligibility may be shown only as explicitly unverified metadata, never certified outcome.

InspectionCode identifiers: INPUT_MISSING, PLATFORM_UNSUPPORTED, PATH_UNSAFE,
NONREGULAR_FILE, FILE_TOO_LARGE, RUN_TOO_LARGE, ENTRY_LIMIT_EXCEEDED, READ_FAILED,
SNAPSHOT_CHANGED, INVALID_UTF8, INVALID_JSON, NONFINITE_VALUE, SCHEMA_INVALID,
CHECKSUM_MISMATCH, ARTIFACT_COVERAGE_MISMATCH, CONFIG_IDENTITY_MISMATCH,
EVENT_HISTORY_MISMATCH, RESULT_MISMATCH, RUN_UNFINALIZED, CANCELLED, INTERNAL_ERROR.
Inspection failures are returned, not raised to the GUI. Unexpected internal exceptions
are converted to INTERNAL_ERROR at the worker boundary and logged without raw data.

## Snapshot acquisition and CLI parity

Read using the existing secure POSIX artifact guards: no-follow directory traversal,
fd-relative O_RDONLY/O_NOFOLLOW/O_NONBLOCK regular-file reads. Never create locks.
Capture each allowed artifact once, in <=64 KiB chunks. All hashes, validation, parsing
and display derive from those bytes; no second filesystem read for display or verification.
Check root identity, entry names and per-file dev/inode/size/mtime/ctime before and after
the entire capture using stat only; rename/replacement/change becomes SNAPSHOT_CHANGED.
Changing the directory after capture cannot change the cached bytes: the integrity badge
explicitly says "Verified snapshot", with load time, not "current files are verified".

Allowed payloads: manifest.json, config.json, command.json, events.jsonl, checksums.json,
client.json, client.stderr, traffic_summary.json. Detect .run.lock/.creation.lock without
reading them. Locks or running state yield unfinalized; do not remove them. Refuse extra
entries for verification; do not follow/read unknown entries, including directories.
Limits: <=16 directory entries, each file <=16 MiB; manifest/config/command/events/checksums
<=1 MiB each; stderr <=1 MiB; all captured bytes <=48 MiB. JSON nesting <=64 levels.
Cancellation checked before opening and between chunks, parsing stages and validation.
Return progress per completed artifact (completed,total), <=16 updates. No elapsed-time
guess is a verification success. Blocking filesystem/kernel hangs cannot be guaranteed
cancelled; local filesystem is the supported scope and this limitation is visible.

Refactor the current verify_run algorithm into one Qt-free snapshot verification routine
in diaglab.inspection, returning the same VerificationResult on success. inspect_snapshot
uses that routine; verify_run calls it through capture_run and maps structured failures
to existing CLI errors. No duplicate schema/hash/reconciliation algorithm in the GUI.
CLI exit parity: 0 for verified snapshots, including intact failed/interrupted runs; 2
for INPUT_MISSING; 3 for invalid/unfinalized snapshots. Existing Phase 1 planned manifests
remain accepted with PLANNED_ONLY. Existing run CLI contracts are preserved.

## Failed and partial evidence

Integrity failures suppress report, numeric metrics and charts. Cached readable raw bytes
remain inspectable as "Unverified raw evidence"; show computed hash plus expected hash
when safely available, and per-artifact matched/mismatched/unlisted/unavailable status.
Hash equality for one file never means the run passed verification. Oversized/unsafe files
show the issue and no content. UTF-8 raw decoding uses explicit replacement for display
only, labelled "replacement characters used"; verification always rejects invalid UTF-8.
Raw view initially renders <=64 KiB per selection, with explicit next-page controls;
search/filter applies to loaded rows, not unrestricted raw content.

Verified failed/interrupted runs with no complete report show unavailable metrics, logs,
state and failure reason. A verified failed run with a valid but unreconciled summary
may show report values, prominently labelled "Traffic result unverified" with its flags.
Unfinalized runs show no charts or derived values, even if a partial summary exists.

## Display model: diaglab.presentation

Qt-free; functions pure, no filesystem/network/subprocess calls. Proposed APIs:

```python
def build_view(inspection: RunInspection) -> RunView: ...
def filter_flows(view: RunView, query: str) -> tuple[FlowRow, ...]: ...
def format_value(value: int | float | None, unit: str, *, reason: str | None = None) -> str: ...
```

RunView: integrity_text, traffic_text, eligibility_text (str each), summary
(tuple[DisplayValue, ...]), flows (tuple[FlowRow, ...]), series (tuple[ChartSeries, ...]),
events (tuple[Mapping, ...]), raw_artifacts (tuple[ArtifactSnapshot, ...]).
DisplayValue: label, text, unit (str), value (int|float|None), evidence
(tuple[EvidenceReference, ...]), unavailable_reason (str|None).
FlowRow: socket_id (int), values (tuple[DisplayValue, ...]), search_text (str).
ChartSeries: label/unit (str), points (tuple[ChartPoint, ...]).
ChartPoint: start_s/end_s (float), value (float|None), omitted (bool), break_before
(bool), evidence (tuple[EvidenceReference, ...]). Null creates a break, never zero.

EvidenceReference: artifact (str), json_pointer (str, RFC6901), sha256 (str), source
(str), derivation (str|None), inputs (tuple[str, ...]). Direct values link to the
exact JSON pointer; derived goodput links to bytes/start/end pointers with derivation
"goodput_bps". Receiver-source identity comes from Iperf3Report. Embedded receiver paths
start /server_output_json; independent server files are not Phase 2 run payloads. Test
fixtures containing independent server data remain parser tests, not newly accepted
viewer artifacts. Do not fabricate a pointer to computed bps in raw JSON.

Formatting: decimal SI, bps displayed as Mbit/s (divide by 1,000,000), durations in s,
RTT in us (label µs), bytes as integer bytes. Floats show three decimal places using
Python fixed-point formatting; integers remain exact. Details also show repr(value) and
unit. Missing values show "Unavailable: REASON", default reason NOT_RECORDED. Table cells
may shorten this to "Unavailable" with the full reason in tooltips and details. Never
invent missing metric values. Summary goodput uses report.receiver.computed_bps; residual
and retransmits use report fields. Formatting never re-derives measurement formulas.

Timeline points show each stream separately with a distinct aggregate series, never
sum aggregate and per-flow data. Use parser interval values; omitted intervals are labelled
warm-up and styled with hatching, excluded from retained summaries. Gap/omission boundary
sets break_before; no interpolation across missing data. Axis labels include time (s),
goodput (Mbit/s), RTT (µs); smoothed RTT is not labelled latency percentile.
Filtering is trimmed case-insensitive literal substring across socket ID, endpoints and
quality text; empty query restores all rows. No expression evaluation or Wireshark syntax.
Sort numeric columns on original values; unavailable values last, stable socket-ID tie-break.

## Qt boundary and lifecycle: diaglab.gui

Proposed entrypoint: diaglab-gui [--run DIR], also python -m diaglab.gui. Missing optional
Qt exits 2 with an install-extra message; Windows exits 2 with Linux-only explanation.
Core imports must not import Qt. GUI modules have no imports/calls to run_experiment,
traffic.runner, subprocess or sockets. No shell fallback or embedded web browser.

MainWindow.open_run(path), cancel_load(), set_theme("light"|"dark") are public test APIs.
One QThread LoadWorker at a time; thread calls load_run with Event cancellation. No parallel
loads; a new open selection first cancels and joins the old worker, then begins the next.
Signals: progress(int,int), finished(RunInspection), failed(InspectionIssue). Results carry
generation IDs; stale/cancelled loads cannot overwrite a newer selection. UI never blocks
waiting for join: cancellation enters "Cancelling" and polls completion via Qt timer.
closeEvent is deferred until worker finishes and QThread is joined; no QThread.terminate.
No thread/file descriptor leaks; all descriptors close in finally blocks.

Offscreen responsiveness test: 20 ms heartbeat, no gap >250 ms while a maximum bounded
local fixture loads. Cancellation/close completes within 2 s on supported local test
filesystem. These are release acceptance bounds for controlled CI tests, not universal
I/O guarantees. Long loads/blocked I/O keep the cancelling window visible, never claim exit.
Keyboard focus order: Open, filter, run/flow list, table, details, raw/log tabs. Ctrl+O
opens a run; Escape cancels active loading; themes are in-memory, no settings files written.

## Dependencies, CI and independent tests

Proposed optional gui extra: PySide6>=6.10,<7. Check wheels/runtime on Python 3.12/3.14
before declaring that range supported; exact tested versions recorded in handoff.
First offline charts use Qt painting of bounded parser series, avoiding a plotting
dependency until its need is demonstrated. No public license is silently selected.
Before distribution, record dependency notices and owner's software-license decision.
Qt reference: https://doc.qt.io/qtforpython-6/gettingstarted.html

TG-01–10 (Claude's canonical checklist) run in headless CI without Qt. TG-11/12 use
explicit pytest.importorskip("PySide6") in that job, visibly reported. Add separate
Python 3.12/3.14 gui CI jobs installing dev+gui extras with QT_QPA_PLATFORM=offscreen;
those jobs require Qt and cannot skip the GUI tests. CLI remains tested without gui extra.
Claude writes tests from these contracts before reading implementation, and reviews
methodology, units, rounding, evidence linkage, themes and cancellation separately.

## Visual implementation review

docs/mockups/index.html provides a local screenshot gallery of the implemented viewer,
with light/dark layouts and failed/interrupted/unfinalized/unavailable cases. All numbers
are synthetic illustrations. Regenerate using docs/mockups/generate.py with dev+gui extras
and QT_QPA_PLATFORM=offscreen. The generator replaces the path label with an explicit
synthetic banner; no private evidence or network resources are used. Owner visual acceptance
and Claude's final implementation review remain pending. The Open dialog stores no history.

CLI verification uses include_evidence=False and never computes display provenance.
Evidence-resolution failures leave integrity unchanged and references empty; the details
panel explicitly reports unavailable references. Cancellation still takes precedence.

### R-27 — warm-up display clock

Retained points keep their raw parser timestamps. Warm-up points receive one constant
nonpositive shift per series so they end at or before the first retained start. Durations,
values and evidence pointers are unchanged. ChartPoint raw_start_s/raw_end_s preserve the
original timestamps; details show both raw and display windows. This separates iperf3's
restarted retained clock from the warm-up phase without overlapping the two phases.

## Accepted review resolutions R-1–R-26

The following resolutions supersede ambiguous draft wording above.

### Resolutions (binding test assumptions)
- **R-1 Code-to-exit mapping (CLI parity).** I pinned these from the current pre-refactor CLI on 2026-10-01 against a real run built by `run_experiment` from the scrubbed captured fixture. The refactor must preserve them:
  - root missing, `manifest.json` missing, or any listed payload missing → `INPUT_MISSING`, exit 2. This includes a missing `client.json` or `checksums.json` in a finalized run.
  - digest mismatch → `CHECKSUM_MISMATCH`, exit 3. An invalid UTF-8 byte appended to `events.jsonl` currently fails here first, and that is acceptable.
  - extra file or directory → `ARTIFACT_COVERAGE_MISMATCH`, exit 3.
  - `.run.lock` or `.creation.lock` present, or `state=running` → `RUN_UNFINALIZED`, integrity `unfinalized`, exit 3. Today `.creation.lock` reports a coverage error; it must now report `RUN_UNFINALIZED`. Exit 3 is unchanged.
  - symlinked payload → `PATH_UNSAFE`, exit 3.
  - offline plan (`run` without `--execute`) → verified, state `planned`, exit 0.
  - Phase 1 `manifest create` directory → verified, reasons `("PLANNED_ONLY",)`, exit 0.
  - intact failed run (connection timeout) → verified, state `failed`, `transfer_completed=false`, `result_verified=false`, exit 0.
- **R-2 Issues are deterministic.** `issues` is non-empty if and only if integrity is not `verified`. Verification stops at its first failure, as `verify_run` does today. Tests check that the expected code is present in `issues` and don't depend on ordering. `verification` is non-null if and only if integrity is `verified`.
- **R-3 Goodput comes only from receiver intervals (methodology).** The current `report.intervals` holds both `direction=sent, source=client` and `direction=received, source=embedded_server|independent_server` intervals; confirmed by experiment: 120 = 30 intervals × 2 directions × (flow + aggregate). The contract's "use parser interval values" is ambiguous, and plotting sender intervals as "goodput" would mislabel sender throughput.
  - Every point in a series whose unit is Mbit/s and whose label contains "goodput" must come from a `direction=received` interval.
  - Sender intervals may be shown only in series labelled "sender".
  - If there are no receiver intervals (`SERVER_OUTPUT_UNAVAILABLE`), goodput series are absent and the run view shows goodput as unavailable. Sender data never substitutes.
  - RTT series come from `direction=sent` per-flow intervals only, and there is no aggregate RTT series. That RTT is smoothed, as the contract already says.
- **R-4 Evidence is resolved in the core, and the test checks it against the bytes.** Pointer resolution lives in `diaglab.inspection`, next to the parser, with no JSON re-walking in `diaglab.presentation`.
  - Test oracle: for every `EvidenceReference`, `sha256` equals that artifact's snapshot hash, and the RFC 6901 pointer resolves within the snapshot bytes.
  - For a direct value, the resolved value equals the displayed value before formatting.
  - For `derivation="goodput_bps"`, the inputs resolve to `bytes`, `start` and `end`, and `bytes*8/(end-start)` matches the value to a relative tolerance of 1e-12.
  - For a missing epoch `sum`, use `derivation="AGGREGATE_DERIVED_FROM_FLOWS"` with the per-flow pointers as inputs.
  - In `events.jsonl`, pointers use a 0-based line as the first token, e.g. `/3/name`. Non-JSON artifacts (stderr) use pointer `""` (the whole artifact).
- **R-5 `format_value` units.**
  - The `unit` argument is the source unit, from the closed set `bps | s | us | bytes | count`. Anything else raises `ValueError`, and so does a `bool` value.
  - Output: `bps` → `f"{v/1e6:.3f} Mbit/s"`; `s` → `f"{v:.3f} s"`; `us` → `f"{v:.3f} µs"`; `bytes` → `f"{v} B"`, an exact integer with no separators; `count` → `str(v)`. A float given as `bytes` or `count` raises `ValueError`.
  - `None` → `f"Unavailable: {reason or 'NOT_RECORDED'}"`.
  - `DisplayValue.unit` holds the display unit: `Mbit/s`, `s`, `µs`, `B` or `count`.
- **R-6 Status vocabulary.**
  - `integrity_text` contains "Verified snapshot", "Integrity failed", "Unfinalized" or "Cancelled".
  - When integrity isn't verified, `traffic_text` contains "unverified".
  - When a report exists with `result_verified=false`, `traffic_text` contains "Traffic result unverified".
  - `eligibility_text` never equals or starts with "Accepted". A schema-valid `accepted` value renders text containing "Unsupported".
- **R-7 Collector coverage in `RunView`.** Add `collectors: tuple[DisplayValue, ...]`, one per manifest `collector_coverage` entry. In Phase 2 each has `value=None` and `unavailable_reason="NOT_IMPLEMENTED_PHASE2"`. None may render as available or 0.
- **R-8 Break rule.** The first point in a series has `break_before=False`. A later point has `break_before=True` if:
  - its `omitted` differs from the previous point's,
  - the previous value is `None`, or
  - its `start_s` doesn't match the previous `end_s` under the parser's own time tolerance (`diaglab.traffic.parser._time_matches`, imported and not redefined).
- **R-9 Sorting API.** Add `sort_flows(rows, column: str, *, descending=False) -> tuple[FlowRow, ...]`, where `column` is a `DisplayValue.label`. Numeric order uses the original values, unavailable values go last in both directions, and ties break by ascending socket ID. An unknown column raises `ValueError`.
- **R-10 Filtering.** Matching uses `query.strip().casefold()` as a literal substring of `search_text.casefold()`. `search_text` includes the socket ID, `host:port` for both endpoints, and the quality flags. Regex metacharacters are literal.
- **R-11 `RunView` for non-verified integrity.** When integrity is failed, unfinalized or cancelled: `summary == flows == series == events == ()`. `raw_artifacts` equals the snapshot artifacts, collectors are `()`, and nothing raises. A verified failed run without a report has `series == ()` and a goodput summary value of `None` with a reason.
- **R-12 Platform check.** Use `sys.platform.startswith("win")`, checked before any `os.open`/`os.stat` on the path. The test monkeypatches `sys.platform` in `diaglab.inspection`'s namespace, via `import sys` or a module attribute.
- **R-13 `load_run` doesn't raise for `Exception` subclasses.** An unexpected exception becomes `integrity=failed` with an `INTERNAL_ERROR` issue whose message doesn't contain `str(exc)` (no raw data). `BaseException` (e.g. `KeyboardInterrupt`) propagates.
- **R-14 Progress.** At most 16 calls. `completed` never decreases, `0 ≤ completed ≤ total`, and `total` stays the same across calls. On a verified load the last call is `(total, total)`, with `total` ≥ the number of payload files present.
- **R-15 Cancellation.** If the event is already set when the call starts, the result is `CANCELLED` with integrity `cancelled`, and no `os.open` is made on any artifact. If the event is set from the progress callback, the result is `CANCELLED`, with no `verification` and no `report`.
- **R-16 Snapshot change.** If a captured file is replaced (by rename) or modified after it has been read, the result is `SNAPSHOT_CHANGED` with integrity `failed`. The test triggers this from inside the progress callback.
- **R-17 Depth and parse codes.** JSON nesting deeper than 64 levels → `INVALID_JSON`. `NaN`/`Infinity` → `NONFINITE_VALUE`. Both exit 3.
- **R-18 Qt test APIs and forbidden imports.**
  - `MainWindow()` takes no arguments and has a `current_view` property (`RunView | None`) and `is_loading() -> bool`, in addition to `open_run`, `cancel_load` and `set_theme`.
  - `diaglab.gui`, `diaglab.inspection` and `diaglab.presentation` must not import `subprocess`, `socket`, `multiprocessing`, `QtNetwork`, `QtWebEngine*`, `QProcess` or `QDesktopServices`. They must not reference `run_experiment` or `diaglab.traffic.runner`.
  - Opening runs and switching theme write no files under an isolated `HOME`/`XDG_CONFIG_HOME`, so no `QSettings`. Qt's own file dialog stores history through QSettings (`QtProject.conf`). The contract must say the Open dialog doesn't persist history; otherwise that is an undeclared write. Reviewed in code, since it can't be tested offscreen without driving the dialog.
- **R-19 GIL risk for the 250 ms heartbeat.** `parse_json` on a 27 MiB iperf3-shaped document took 0.43 s here. The `object_pairs_hook` runs Python code, so the GIL should switch between objects, but plain `json.loads` holds it for about 0.16 s per 27 MiB. If TG-11 fails on the maximum fixture, that is a contract decision for Denis (relax the bound, or parse in chunks). It is not grounds to weaken the test quietly.
- **R-20 Signals.** Integrity and cancellation outcomes arrive through `finished(RunInspection)`. `failed(InspectionIssue)` is only for `INTERNAL_ERROR` at the worker boundary.
- **R-21 Eligibility on failed integrity.** Shown only inside text containing "unverified".
- **R-22 Read-only test scope.** Before/after comparison covers entry names, content sha256, size, mode, inode, mtime and ctime, but not atime, which reads legitimately update under `relatime`.

- **R-23 Summary labels and units for text values.** Summary `DisplayValue` labels contain the keywords `goodput`, `residual`, `retransmit` and `quality` (casefolded) for those four values, one each. Flow RTT labels contain `mean`/`min`/`max`. Values with no numeric unit (quality flags, collector rows) use `unit=""`. The quality-flags value lists every `report.quality_flags` entry verbatim in its text.
- **R-24 GUI entry check order.** `python -m diaglab.gui` checks the platform before importing Qt. On Windows it exits 2 with a Linux-only message, even if Qt is also missing. On Linux without Qt it exits 2 with an install-extra message that names `gui`, and no traceback.
- **R-25 GUI CI cannot skip.** The GUI CI jobs set `NDPL_REQUIRE_GUI=1`. `tests/inspection/test_gui_qt.py` then imports PySide6 directly, so a missing Qt fails the job instead of skipping. Without the variable, the module is skipped visibly (shown by `-ra`).


## R-26: outcome coherence in shared verification

Planned: execute false; transfer_completed/result_verified false; returncode, timeout_stage
and failure_reason null; eligibility pending. Completed: existing transfer evidence checks,
failure_reason/timeout_stage null, eligibility pending. Failed/interrupted: failure_reason
non-null, result_verified false, eligibility rejected. Failed transfer_completed true requires
a written traffic_summary.json. Interrupted records created before this revision retain
compatibility for the previous flag-before-summary window; new writes set the flag after
summary persistence. Violations map to RESULT_MISMATCH, exit 3. Recorded config validation
errors map to SCHEMA_INVALID, exit 3; config validate remains exit 1.

P2-F1 resolution: bound summary bytes before writing; overflow produces a failed run with
SUMMARY_OUTPUT_LIMIT_EXCEEDED and preserved raw evidence. Any later finalization failure
attempts a failed, rejected emergency manifest with FINALIZATION_FAILED and preserved
cleanup status. Such partial evidence is inspectable but is not claimed integrity-verified.
