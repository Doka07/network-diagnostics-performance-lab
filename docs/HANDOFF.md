# Phase 1 implementation handoff

## Current status — 2026-10-01

Gemini's regression updates are complete. Codex independently ran the current suite:
**134 passed in 1.61s**. Full-project lint and formatting also pass. Gemini's canonical
review approves implementation and regressions. Claude independently re-ran all 134 tests,
verified lint/formatting, inspected the regression bodies, and closed code/test review
with no blocking findings. Both independent reviews are complete.
Remote CI and owner acceptance remain outstanding. The folder is not yet a Git repository
and has no remote; remote CI needs repository setup and an authorized push to a selected
destination. No later phase is opened by this update.

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
