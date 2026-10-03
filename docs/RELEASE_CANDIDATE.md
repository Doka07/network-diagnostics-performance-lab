# Software release and receiver lifecycle follow-up

The released software includes the Linux desktop inspector, saved-run HTML/JSON export, shared
snapshot verification and runner audit corrections. It does not complete telemetry, fault, diagnostic
rules or held-out evaluation phases. No retained performance claim is available.

## Review before committing

The GUI/results release is committed at `25b677a3` and its
[GitHub Actions run passed](https://github.com/Doka07/network-diagnostics-performance-lab/actions/runs/37052132024).
Code and methodology reviews approved that implementation with 483 tests per runtime.
The PREVIEW-1 correction
passes its generator assertions and all 70 results tests; independent confirmation of
that corrected preview is now recorded by both reviewers: PREVIEW-1 is closed.

The current uncommitted follow-up adds receiver lifecycle/finalization tooling, a bounded
Windows operator, four probe regressions, 77 lifecycle/finalization tests and diagnostic
documentation. Codex reran all 564 tests on each of Python 3.12.3 and 3.14.8 with Qt
required: 564 passed per runtime, none skipped.
Lint, formatting and isolated wheel/sdist build pass. Prior CI does not cover
these uncommitted additions. After owner-disabled AC sleep and SSH restart, clean one-
and four-stream pilots completed; see [hardware diagnostics](HARDWARE_DIAGNOSTICS.md).
Receiver flags and probe remain unchanged. A supplied-aggregate parser correction retains
actual per-flow windows and flags differences. New operator/parser code has development
validation; fresh independent approval is not yet recorded.

Follow-up closeout order:

1. Completed: Claude and Gemini approved the corrected [results preview](mockups/results.html),
   including the explicit synthetic banner and preserved fixture labels.
2. Denis reviews the lifecycle follow-up and executes the commit/push commands below.
3. All four CI jobs pass for that new commit.
4. Denis approves the [LinkedIn draft](../publication/LINKEDIN_POST.md) and chosen
   screenshot before publication. Keep the synthetic-data banner visible.

This closes the offline software milestone, not the complete experimental roadmap.

Read the current [handoff](HANDOFF.md) for reviewer verdicts and remaining gates. Open
[the synthetic preview gallery](mockups/index.html) or launch the actual application:

```bash
cd ~/Desktop/network-diagnostics-performance-lab
.venv/bin/diaglab-gui
```

The [viewer guide](GUI_GUIDE.md) covers installation, statuses and evidence links.
The lifecycle follow-up is uncommitted; commands below are for Denis. Codex has not
staged, committed or pushed it. The existing GUI/results release is already published
to the repository; the LinkedIn draft has not been posted.

## Owner commit and push

Review the changes, including newly added source, tests and screenshots:

```bash
git status --short
git diff --stat
git diff --check
git diff
```

After acceptance, stage the specific public project paths. Private canonical reviews and
measurement artifacts are private (outside the repository or in ignored `artifacts/`)
and are not included:

```bash
git add scripts/receiver_lifecycle.py scripts/windows_receiver.ps1
git add scripts/diagnostic_finalize.py scripts/windows_diagnostic.py
git add diaglab/traffic/parser.py docs/PHASE2_CONTRACTS.md
git add README.md
git add tests/lifecycle tests/integration/test_probe_server.py tests/README.md
git add docs/RECEIVER_LIFECYCLE.md docs/HARDWARE_DIAGNOSTICS.md
git add docs/DECISIONS.md docs/HANDOFF.md docs/REVIEW_LOG.md docs/RELEASE_CANDIDATE.md
git add docs/MASTER_PLAN.md
git add publication/CLAIMS.md publication/LINKEDIN_POST.md
git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
```

Inspect the staged file list and diff, then:

```bash
git commit -m "Add diagnostic finalization and fix parallel iperf interval parsing"
git push origin main
```

## Remote verification

On [GitHub Actions](https://github.com/Doka07/network-diagnostics-performance-lab/actions),
open **Python validation** for the newly pushed commit. All four jobs must succeed:

- `offline-checks (3.12)` and `offline-checks (3.14)`: core installation, lint, formatting,
  configuration validation, independent tests and package build.
- `gui-checks (3.12)` and `gui-checks (3.14)`: GUI extras, offscreen Qt tests with
  `NDPL_REQUIRE_GUI=1` so missing Qt cannot silently skip the GUI checks.

Optional Qt tests may skip only in the core-only jobs. A green older commit does not
validate this candidate. Local passing tests do not replace remote CI or owner acceptance.

## Next project milestone

The bounded one/four-stream pilots have completed with verified cleanup. Confirm remaining
inventory/topology notes and plan the retained baseline separately; do not publish pilot
numbers as a validated benchmark or assert a single proven cause for the earlier stalls.
Collectors, fault injection and automatic diagnosis follow their separate reviewed contracts
and phase gates; the offline viewer's success does not authorize those experiments.
