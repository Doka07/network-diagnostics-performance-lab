# Independent tests

Claude owns independent test authoring for all phases (standing assignment, 2026-10-01).
Phase 1 tests below were authored by Gemini and are retained unchanged.

Phase 1 tests authored and passing:
- `TC-U-01` (`tests/unit/test_config.py`): Strict YAML parsing, safe defaults, rejection of duplicate keys, unsafe tags, anchors/aliases, nonfinite floats, unknown fields, and cadence limits.
- `TC-U-02` (`tests/unit/test_config.py`): Safety preflight logic, RFC 1918 IPv4 unicast validation, interface allowlist check, rejection of public, multicast, broadcast, and loopback targets.
- `TC-U-03` (`tests/unit/test_metrics.py`): Metric batch validation, RFC 3339 UTC timestamps, monotonic ordering, duplicate series rejection within an epoch, lossless round trips, flattening, and tag whitelist enforcement.
- `TC-U-04` (`tests/unit/test_manifest.py`): Manifest generator, structure, run ID formatting, SHA-256 calculation, and regular file hashing.
- `TC-U-04B` (`tests/unit/test_manifest.py`): Path traversal (`../`), absolute paths, Windows drive/backslash paths, symlink rejection in paths and roots, mode 0600 file creation, and refusal of populated or symlinked destination directories.
- `TC-I-01` (`tests/integration/test_cli.py`): CLI subcommand execution, exit codes (0, 1, 2), refusal to overwrite populated destinations, symlink refusal, `--version`, and entrypoint consistency.

Phase 2 tests (authored by Claude under the owner's reassignment; scrubbed captured
fixtures and their provenance under `tests/fixtures/iperf3/` were prepared by Gemini):
- `TC-U-05` (`tests/unit/test_traffic_parser.py`): direction from key path rather than the
  misleading `sender` flag, receiver-source precedence, captured-anomaly regressions, error
  classification, nonfinite numbers, 1/4-stream aggregation without double counting.
- `TC-U-06` (`tests/unit/test_traffic_parser.py`): RTT presence/unavailability, omit
  metadata and omitted/retained split, goodput and rate-tolerance arithmetic.
- `TC-I-02` (`tests/integration/test_traffic_runner.py`): real mock-executable lifecycle,
  process-group ownership, connect vs execution deadline, SIGTERM->SIGKILL escalation,
  output caps with preserved prefix, idempotent wait/stop, unknown handles, single-use
  adapters, offline planning without subprocess/socket activity, SIGINT interruption and
  finalization-failure exception chaining.

Audit regressions (`tests/inspection/test_audit_regressions.py`, contract-first, before
Codex's production fixes):
- `AUD-01`: executed child inherits no blocked/ignored SIGINT/SIGTERM; SIGTERM-responsive
  children end on SIGTERM at the deadline and after interruption; SIGTERM-ignoring
  children are still escalated to SIGKILL.
- `AUD-02`: outcome coherence for planned/failed/interrupted/completed records, with
  legitimate evidence of every state still verifying.
- `AUD-03`: invalid recorded configuration is artifact-invalid (verify exit 3) while
  `diaglab config validate` keeps exit 1.

GUI steps 1-2 (`tests/inspection/`, written from docs/GUI_CONTRACTS.md plus Claude's
resolutions R-1..R-26 before any implementation existed):
- `runs.py`/`conftest.py`: run-directory matrix produced by the accepted Phase 2
  `run_experiment` with a mock iperf3 (captured fixtures with RFC 1918 test-address
  substitution, plus synthetic 1/4-stream, omitted, gap, derived-aggregate and
  no-server documents). Tampered variants are derived from these.
- `TG-02/03/04/06/07` (`test_snapshot_integrity.py`): single-snapshot consistency, CLI
  exit-code parity pinned from pre-refactor `diaglab verify`, failed/partial evidence,
  read-only loading, hostile inputs, platform refusal, cancellation and progress.
- `TG-01/05/08` (`test_presentation.py`): value fidelity against raw JSON, receiver-only
  goodput charts, missing data, evidence pointers, formatting, filtering and sorting.
- `TG-09/10` (`test_boundaries.py`): no Qt in core imports, no process/network/runner
  path in viewer code, optional `gui` extra.
- `TG-11/12` (`test_gui_qt.py`): offscreen Qt responsiveness, cancellation, close
  deferral and smoke checks. Skipped visibly without PySide6; GUI CI jobs set
  `NDPL_REQUIRE_GUI=1` so a missing Qt fails instead of skipping.

Review regressions (`tests/inspection/test_review_regressions.py`, from Claude's review
findings):
- `P2-F1`: an oversized derived summary ends as a finalized, verifiable failed run; the
  largest fitting summary still completes; finalization failure leaves a terminal manifest.
- `CORE-1`: a `sum` window inside the parser's time tolerance verifies through
  `diaglab verify` and the viewer, and evidence cites the `sum` actually used; provenance
  failure never changes integrity.
- `CHART-1` (proposed R-27): after iperf3's post-omit clock restart, warm-up and retained
  timeline points never share a time span; retained points keep raw parser time.
- `FAIL-1`: a verified failed or interrupted run shows its recorded failure reason in the
  traffic status or summary, not only inside the event log.
- `UI-1` (`test_gui_qt.py`): link colours, including colours written into rich text, reach
  4.5:1 on the panel in both themes, also after a theme switch with a run loaded.
- `ZERO-1`: a measured zero-byte receiver interval is a 0 bit/s value with evidence, not
  "Unavailable" and not a line break. `SHIFT-1`: the R-27 warm-up shift is per series
  (client and embedded server clocks may differ by sub-millisecond amounts).
- `test_gui_qt.py` round 3: negative warm-up bounds in details have no sign collisions;
  the drawn line never bridges an interval gap (pixel check with a no-break control);
  `UI-2` flow identity stays readable beside unavailable RTT cells, whose full reason
  remains reachable by tooltip or details.
- `N-1` (`test_gui_qt.py`): a self-consistent `command.json` whose `failure_reason` holds
  markup is shown literally in plain-text status labels (rendered-width check with a
  rich-text control), never as a link or hidden comment.

Saved-run results report (`tests/results/`, written from docs/RESULTS_CONTRACTS.md plus
Claude's resolutions RR-1..RR-8 before `diaglab.results` existed; inputs come from the
accepted runner with a mock iperf3):
- `RT-00`: the fixture matrix is checked against the accepted core alone.
- `RT-01`: metrics are exact parser copies; goodput evidence resolves in the source bytes;
  runs are never pooled; source digests equal the snapshot's.
- `RT-02`: a measured zero is numeric zero; unavailable rows are all-null with a code; the
  HTML never renders a missing value as zero.
- `RT-03`: missing, tampered, unfinalized, planned, failed and interrupted inputs become
  honest rows (exit 0); unverified metadata is null.
- `RT-04`: evidence kind and run role are copied; nothing claims acceptance.
- `RT-05`: inputs are never mutated and each is captured once.
- `RT-06`: three 0600 files; output overlap, nonempty or symlinked output, duplicate paths
  (including inputs without a verified run ID), repeated run IDs and more than 32 inputs
  are refused before anything is created.
- RT-02/03 include a verified run with receiver data but an unverified traffic result
  (interval gap): its metrics must stay null.
- `inspection/runs.py`: `RunBuilder` raises when a fixture run was refused before creation
  (no manifest), instead of returning a nonexistent directory.
- `RT-07`: no paths, IDs, addresses, ports, commands, stderr, event content, free-form
  reasons or raw JSON; a closed JSON structure; inert, self-contained, escaped HTML.
- `RT-08`: the CLI announcement, summary/build parity, bundle checksums, usage exit 2 and
  write-failure exit 3 without final checksums.

Later privileged tests require explicit provisioning and approval; they never execute
against the controller's live network from ordinary CI.
