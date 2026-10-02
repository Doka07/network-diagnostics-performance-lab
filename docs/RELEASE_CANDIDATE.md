# Offline GUI and results release candidate

This candidate adds the Linux desktop inspector, saved-run HTML/JSON export, shared
snapshot verification and runner audit corrections. It does not complete telemetry, fault, diagnostic
rules or held-out evaluation phases. No retained performance claim is available.

## Review before committing

Code and methodology reviews approve the GUI and results implementation. Reviewers
reported 483 passing tests on each of Python 3.12 and 3.14. The PREVIEW-1 correction
passes its generator assertions and all 70 results tests; independent confirmation of
that corrected preview is now recorded by both reviewers: PREVIEW-1 is closed.

Final closeout order:

1. Completed: Claude and Gemini approved the corrected [results preview](mockups/results.html),
   including the explicit synthetic banner and preserved fixture labels.
2. Denis accepts the visual result and executes the commit/push commands below.
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
The reviewed code is uncommitted; all commands below are for Denis to execute after
review acceptance. Codex has not staged, committed or pushed it.

## Owner commit and push

Review the changes, including newly added source, tests and screenshots:

```bash
git status --short
git diff --stat
git diff --check
git diff
```

After acceptance, stage the specific public project paths. Private canonical reviews and
measurement artifacts live outside this repository and are not included:

```bash
git add .github/workflows/ci.yml AGENTS.md CLAUDE.md GEMINI.md README.md pyproject.toml
git add diaglab/run.py diaglab/inspection.py diaglab/presentation.py diaglab/verification_support.py diaglab/gui
git add docs/ARCHITECTURE.md docs/DECISIONS.md docs/GUI_PLAN.md docs/GUI_CONTRACTS.md docs/GUI_GUIDE.md
git add docs/HANDOFF.md docs/LIMITATIONS.md docs/MASTER_PLAN.md docs/PHASE2_CONTRACTS.md docs/REVIEW_LOG.md
git add docs/RELEASE_CANDIDATE.md docs/mockups tests/README.md tests/inspection
git add diaglab/cli.py diaglab/results.py docs/RESULTS_CONTRACTS.md docs/CONTRACTS.md docs/CLAIM_LEDGER.md publication tests/results
git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
```

Inspect the staged file list and diff, then:

```bash
git commit -m "Add offline GUI and results export with verified evidence"
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

After GUI acceptance and green CI, close the outstanding Phase 0 inventory/topology notes
and review bounded one/four-stream runner pilots. Live traffic needs its concrete approval.
Collectors, fault injection and automatic diagnosis follow their separate reviewed contracts
and phase gates; the offline viewer's success does not authorize those experiments.
