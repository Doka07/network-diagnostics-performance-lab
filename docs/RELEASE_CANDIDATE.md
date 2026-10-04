# Software and pilot closeout

The reviewed software is committed at `45404309ef3965cf07f784f941259c384fdfc5d8`.
[All four CI jobs passed](https://github.com/Doka07/network-diagnostics-performance-lab/actions/runs/37139253231).
Two bounded real pilots completed with verified cleanup. Windows need not be connected
for the remaining documentation, tests, offline viewing or CI.

Claude approved the final code and added 17 independent parallel-interval regression
cases. He reports 581 passing on each of Python 3.12.3 and 3.14.8. Gemini verified the
pilot arithmetic and reviewed publication claims/visuals. Current validation and any
limitations are recorded in [HANDOFF.md](HANDOFF.md).

The remaining candidate consists of Claude's new tests/catalog entry and reconciled
documentation. Production code and raw evidence are unchanged. The owner alone commits,
pushes and publishes. No files have been staged by Codex.

## Owner commit and push

Run from the project directory. Explicit paths exclude raw runs and private reviews:

```bash
cd ~/Desktop/network-diagnostics-performance-lab
git status --short
git diff --check
git add tests/unit/test_parallel_intervals.py tests/README.md
git add publication/CHATGPT_CANVA_BRIEF.md publication/CLAIMS.md
git add docs/GUI_GUIDE.md docs/RECEIVER_LIFECYCLE.md
git add docs/HANDOFF.md docs/REVIEW_LOG.md docs/RELEASE_CANDIDATE.md
git diff --cached --check
git diff --cached --stat
git diff --cached
```

After reviewing the staged changes:

```bash
git commit -m "Add independent parallel-interval regressions and publication briefing"
git push origin main
```

## Remote verification

Open [GitHub Actions](https://github.com/Doka07/network-diagnostics-performance-lab/actions)
and select **Python validation** for your new commit. All four jobs must pass:

- offline-checks (3.12)
- offline-checks (3.14)
- gui-checks (3.12)
- gui-checks (3.14)

The GUI jobs require Qt and run inspection tests; offline jobs run the core suite and
build packages, with GUI checks allowed to skip when Qt is absent. Do not describe each
CI job as running all 581 tests. Green CI on an older commit does not cover new tests.

## ChatGPT and Canva

Upload [CHATGPT_CANVA_BRIEF.md](../publication/CHATGPT_CANVA_BRIEF.md) to ChatGPT. It
contains the prompt, exact results, source links, limitations and visual guidance.
Use a real screenshot labelled as pilot data; redact local paths and endpoints without
hiding flags/status. Synthetic mockups retain their synthetic labels. Denis decides the
final text and visual and publishes himself.

This completes the software-and-bounded-pilot milestone, not the entire experimental
roadmap. Retained campaigns, telemetry, fault injection and automated diagnosis are
future work with separate contracts and experiment approvals.
