# Implementation handoff

## Current update — Phase 2 CI fixture fix ready

GitHub Actions run 36913304350 failed on both Python versions with 197 passes and one
failure: the SIGINT integration test omitted its fake executable argument, selecting
system iperf3, which is absent on CI. Claude corrected the argument and audited every
run_experiment test call; assertions and production code are unchanged.
Codex verified the normal suite: 198 passed in 4.18s; lint/formatting and diff checks pass.
Owner commit/push and a new successful remote CI run remain pending.

## Previous local review status

## Current status — Phase 2 local code/test review complete

Codex read Claude's final canonical update. Claude corrected the regression's executable
argument, removed its xfail after verification, and confirmed all three implementation
corrections. His final verdict has no blocking or remaining code finding. His reported
normal suite is 198 passed, zero skips/xfails; lint/formatting and package build pass.
Codex independently reran the normal suite: 198 passed in 4.02s, with no overrides.
Full-project lint, formatting and git diff checks also passed.

Claude performed both independent test authoring and code review under Denis's explicit
reassignment. Gemini's saved approval covers contracts only; a separate Gemini implementation
review does not exist. Do not describe this as two completed implementation reviews.
The GUI proposal is approved by Claude; GUI implementation has not started.

Next: owner commits/pushes when ready, then verify Phase 2 remote CI. Owner acceptance
and separately authorized hardware pilots remain pending. No new phase, live traffic,
commit or push follows automatically from these local results.

## Previous correction handoff — retained history

## Active update — Claude test handoff and review corrections

Denis reassigned Gemini's Phase 2 test authoring to Claude after repeated agent failures.
Claude added 64 tests (TC-U-05/06 and TC-I-02), preserving Gemini's scrubbed fixtures.
Claude reports 197 passed and one strict xfail, no blocking code finding, and approves
the GUI proposal's scope/sequencing. Test authoring and code review share one reviewer
for this assignment; standing future roles are unchanged.

Codex corrected all three reported items: finalization now preserves a prior failure in
its exception chain (and prioritizes cleanup exit 4); numeric JSON rejection uses a typed
NonfiniteValueError instead of message matching; omission mismatch failure disposition is
documented. Claude's tests and private verdict are unchanged by Codex.

Claude: verify these fixes, confirm the regression now passes, and remove only its stale
strict xfail marker after verification. Update the existing canonical review file with
final test results and implementation verdict. Correct the statement implying Gemini
posted a Phase 2 code review: Codex found only contract approval in Gemini's current file.
The finalization regression creates mock_executable but omits executable=str(mock_executable)
in its run_experiment call. Thus the unmodified test selects installed iperf3 and its
original failure reason is PROCESS_NONZERO_EXIT, not the asserted CONNECTION_TIMED_OUT.
Fix this fixture wiring before removing xfail. Codex verifies the intended case using a
temporary pytest plugin selecting that mock, without editing independent test files.
Verification with that override and --runxfail: 198 passed in 3.90s; full-project lint,
formatting and diff checks passed. This is conditional development verification: the
canonical suite still needs Claude's fixture correction and marker removal to pass normally.
GUI implementation and hardware pilots remain unopened; no additional live traffic ran.
Remote CI and owner acceptance remain pending.

## Previous implementation handoff

## Active handoff — Phase 2 implementation, independent review pending

Both reviewers approved docs/PHASE2_CONTRACTS.md; Denis then authorized implementation.
Implemented baseline pilot runner, strict receiver parser, bounded process-group cleanup,
durable raw artifacts/checksums, offline planning and verification, and run/verify CLI.
One/four streams are supported. Telemetry, faults and diagnosis remain unimplemented.
No additional LAN traffic, commit or push was performed in this implementation round.

Gemini: author TC-U-05, TC-U-06 and TC-I-02 against docs/PHASE2_CONTRACTS.md. Own only
tests/; use scrubbed captured JSON with provenance. Cover one/four streams, endpoint
selection, omitted intervals, numeric guards, partial output, output caps, watchdog,
SIGINT/SIGTERM cleanup, repeated wait/stop, unknown handles and offline behavior.
Update ../ndpl-private/GEMINI_PLAN_REVIEW.md in place, current verdict first.

Claude: review diaglab/traffic/, diaglab/run.py, diaglab/artifacts/store.py, CLI and new
schemas against the approved contract. In particular inspect process ownership during
startup/interruption, cleanup failure priority, durable finalization, closed artifact
coverage and independent re-parsing. Read Gemini's tests when available. Update
../ndpl-private/CLAUDE_PLAN_REVIEW.md in place, current verdict first. No live traffic.

Development checks use mocked route/probe functions and local fake subprocesses; they
exercise success, connection failure, watchdog escalation, prefix preservation and offline
behavior. They do not replace Gemini's independent Phase 2 suite or Claude's code verdict.
Local validation: existing independent suite 134 passed; Ruff check and formatting clean;
wheel and source distribution built successfully with the new modules and schemas included.
Separate mock-child checks also verified SIGINT (130) and SIGTERM (143), finalized
interrupted artifacts, re-parsing/integrity verification and successful cleanup.
Phase 1 remains accepted. Phase 2 acceptance, new remote CI and hardware pilots are pending.
Phase 0 inventory supplement and physical topology/shared traffic remain open.

## Previous handoff — retained history

## Phase 2 contract review draft

Codex read both reviewers' latest readiness findings and Gemini's TC-U-05/TC-U-06/TC-I-02
specifications. Concrete parser, runner and CLI APIs are now documented in
[PHASE2_CONTRACTS.md](PHASE2_CONTRACTS.md). No Phase 2 production implementation, new tests,
additional traffic, commit or push was performed in this contract round.

Claude: review the new draft against your six-item checklist, particularly the persistent
server requirement for a separate pre-connect probe and legacy iperf3 timeout observability.
Recheck Finding 2 against the original raw summary: its seconds matches end-start; specify
any differing nested path precisely. Record an explicit contract verdict and remaining
requirements in ../ndpl-private/CLAUDE_PLAN_REVIEW.md, latest status first.

Gemini: reconcile TC-U-05/TC-U-06/TC-I-02 with the named APIs, return fields and error mapping
in the draft. Review the timeout observability decision before coding lifecycle assertions.
Do not infer packet loss or unacknowledged buffer state from endpoint byte residuals.
Prepare scrubbed captured-regression fixture provenance as specified; executable tests
follow contract decisions and the owner-authorized phase scope. Update the existing
../ndpl-private/GEMINI_PLAN_REVIEW.md in place, latest verdict first.

Both reviews confirmed private readiness evidence and checksum validity. The old inventory
snapshot remains immutable; future refresh uses a new timestamped supplement. Physical
topology/shared traffic remain unconfirmed. Phase 0 is not declared fully closed.

## Current status — 2026-10-01

Phase 1 is accepted and closed. The owner then explicitly authorized a scoped manual
30-second, one-stream Ubuntu-to-Windows readiness check. It completed successfully;
both endpoint outputs and raw checksums were verified, and cleanup was verified.
The initial connection-only failure is retained separately. No retained performance
campaign, fault injection, or Phase 2 implementation was executed.

Private evidence for agents (relative to the repository):
- Successful check: ../ndpl-private/artifacts/phase0/manual-22e6e921fc594eb8b9c94e5cbadeff21/
- Failed connection attempt: ../ndpl-private/artifacts/phase0/manual-91ac1d7eab8d4d78a58d4ce9abb4e2e2/

Read summary.json, client.json, server.json, cleanup.json, SHA256SUMS, and the saved
operator scripts. The temporary server must remain attached to a live SSH session;
the successful attempt verified its listener from a separate session before traffic.
The Linux client JSON's sum_received.sender flag is misleading in this version pair:
identify the receiver by endpoint/direction and compare the independent server result.
The receiver byte count and duration agree exactly between the two endpoint outputs.

Next agent assignments:
- Claude: review readiness evidence, bounded setup/cleanup, and the SSH process lifetime
  finding. Review the proposed Phase 2 scope below and record requirements/blockers in
  ../ndpl-private/CLAUDE_PLAN_REVIEW.md, latest status first. Do not execute traffic.
- Gemini: independently verify checksums, endpoint byte/duration agreement and goodput
  arithmetic. Keep this single result separate from retained benchmark claims. Prepare
  independent Phase 2 cases TC-U-05, TC-U-06 and TC-I-02 in the existing canonical review
  file; test code can follow after concrete parser/runner APIs are documented. Do not
  change production code or run additional traffic.
- Codex: next prepare concrete Phase 2 interfaces/CLI contracts, then implement the
  assigned runner after the phase gate. Commits and pushes remain owner-only.

Proposed Phase 2 scope: baseline-only iperf3 traffic adapter, bounded owned process-group
lifecycle and cleanup, strict finite JSON parsing, one/multiple stream reconciliation,
receiver goodput and per-flow smoothed TCP RTT when available, durable raw outputs,
checksums, and run/verify CLI commands. Dry-run/config validation must not transmit;
missing or partial endpoint data must not become a successful result. Collector protocols
remain unimplemented and declared telemetry must not be falsely marked collected.
Hardware pilots and extra traffic need their own concrete authorization. Physical LAN
topology, shared traffic, and remaining host inventory must still be confirmed before
declaring the whole Phase 0 readiness gate closed.

## Phase 1 review history

Gemini's regression updates are complete. Codex independently ran the current suite:
**134 passed in 1.61s**. Full-project lint and formatting also pass. Gemini's canonical
review approves implementation and regressions. Claude independently re-ran all 134 tests,
verified lint/formatting, inspected the regression bodies, and closed code/test review
with no blocking findings. Both independent reviews are complete.
The owner pushed the repository; the first CI run failed before tests because artifacts/
in .gitignore also excluded diaglab/artifacts source modules. The corrected /artifacts/
rule ignores only top-level inventory, and Ruff now explicitly recognizes diaglab as
first-party. Include all three diaglab/artifacts Python files in the owner's next commit.
Local lint/formatting and all 134 tests pass. Successful remote CI and owner acceptance
remain pending. No later phase is opened by this update.

Latest update: the owner committed and pushed the fix. GitHub Actions run
[36891615038](https://github.com/Doka07/network-diagnostics-performance-lab/actions/runs/36891615038)
passed every check in both Python 3.12 and 3.14 jobs. Remote CI is verified.
Owner acceptance is the only remaining Phase 1 gate item. This verifies Linux CI under
both Python versions; Windows execution remains unverified.

The owner subsequently accepted Phase 1 explicitly. **Phase 1 is closed.** Next work
is completing host readiness and preparing the bounded manual transfer, followed by
the Phase 2 traffic runner. No performance evidence has been collected yet.

Reviewers post status directly to ../ndpl-private/CLAUDE_PLAN_REVIEW.md and
../ndpl-private/GEMINI_PLAN_REVIEW.md respectively, latest verdict first with dated history
retained. Codex reads both files; the owner need not paste agent responses.

Phase 1 implements offline configuration validation, immutable metric batches,
strict versioned schemas, planned manifests, secure artifact hashing, and the CLI.
Collector, traffic, injector, analyzer, and privilege boundaries are protocols only.
No command starts traffic, collects live telemetry, applies faults, or diagnoses a run.

## Verification

Initial implementation verified locally on Ubuntu with Python 3.12:

- Gemini's independent suite: `pytest -q` — 88 passed.
- `ruff check .` and `ruff format --check .` — passed.
- `python -m build` — wheel and source distribution built successfully.
- Example configuration validation — passed.

The current tests cover configuration and safety rules, metric round trips,
manifest/hash handling, traversal and symlink refusal, and CLI behavior. Passing tests
do not replace independent code review. Windows execution, Python 3.14 execution,
and remote CI remain unverified.

## Preliminary review correction handoff (historical; test updates now completed)

Codex confirmed and corrected Claude's IMPL-B-1 through IMPL-B-4. Strict numeric YAML
resolution now accepts JSON numeric forms only. Run role can be selected independently
through the APIs and CLI (`--run-role`); standalone planning defaults to pilot for every
evidence kind. Campaign identity is mandatory for every metric batch. Known scenario
branches now report their specific missing fields instead of a generic union failure.

Current independent-suite result after corrections: **79 passed, 9 failed**. Production
lint and full-project formatting pass. Gemini's tests have not been modified by Codex.
Eight metric failures share a fixture missing the now-required `campaign_id`; one manifest
test expects the removed evidence-kind-to-role inference. These are reported for independent
review and correction, not bypassed or silently weakened.

Gemini: add campaign identity to valid metric fixtures, replace inferred-role expectations
with explicit selection and independent-axis checks, and add regressions for all four
blockers. Cover leading-zero/hex/sexagesimal/underscore numeric forms, missing campaign
identity in both run and session records, all run roles across evidence kinds, invalid
roles, and actionable missing scenario fields. Also cover bounded tags, non-dry-run profile
requirements, and CLI unexpected-error handling. Ensure negative tests begin with otherwise
valid fixtures so unrelated schema errors cannot mask the intended behavior.

Claude: verify the corrections and completed docs/tests. Documentation/no-tests findings
were timing-related and are now resolved. Nonblocking changes also restore Claude's role
in dispute routing, bound tags (32 entries, 128-character keys, 256-character strings),
require a profile identifier when dry_run is false, return code 3 for unexpected CLI
exceptions, and sort reported errors by their displayed absolute paths.

Phase 1 is awaiting independent regression updates, final reviewer verdicts, and owner
acceptance. The initial 88-pass result is historical and does not describe the corrected
suite's current status.

## Claude review

Review implementation against the approved Phase 1 contracts and independent tests.
Focus on configuration parsing, schema semantics, file ownership and path handling,
CLI error codes, reproducibility fields, and whether planned artifacts can be mistaken
for measured evidence. Report concrete blockers, affected files, and verification needs.
Update the existing private `CLAUDE_PLAN_REVIEW.md` in place with a dated implementation
review and current verdict; preserve previous history. Do not create another review file.

## Gemini review

Confirm the Phase 1 test matrix and run the suite independently. Add tests for material
contract gaps you find, without changing production code. Update the existing private
`GEMINI_PLAN_REVIEW.md` in place with the current verdict and dated results; preserve
previous history. Do not create another review file.

## Readiness work

Operator-provided Windows inventory reports an active 1 Gbps Ethernet adapter and
Python 3.14.5. `iperf3` was not found in PATH. Ubuntu reports a 10 Gbps local link;
the Windows endpoint limits the negotiated Ethernet path to at most 1 Gbps, before
protocol overhead. No throughput baseline has been measured.

Complete the remaining host inventory and reviewed traffic readiness steps before
measurement phases. The manual Windows inventory script remains untested on Windows.
Live fault injection and publication retain their separate phase gates.
