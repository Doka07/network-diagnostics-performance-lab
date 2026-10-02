# Working agreement

Read docs/MASTER_PLAN.md, docs/CONTRACTS.md, docs/DECISIONS.md and docs/HANDOFF.md before work.
Explicit project-owner instructions take precedence. Implement only the assigned phase.

- Codex implements, performs development checks, runs independent tests, and fixes accepted issues.
- Claude authors committed independent tests and reviews architecture, code, safety,
  documentation, methodology, arithmetic, chart fidelity and conclusions for all phases.
- Gemini is the second independent methodology and GUI reviewer, including arithmetic,
  chart fidelity and interpretation. Claude retains existing independent test ownership.
- The project owner approves experiments, scope, datasets, merges and publication.

Use separate branches/worktrees for concurrent changes. Do not edit the same file concurrently.
Tests disputed by Codex go to Claude first;
unresolved disagreements go to the project owner.
Never silently delete or weaken another agent's tests.

Maintain one existing review file per agent across rounds. Update its current verdict first
and retain dated history; do not create a file for each re-review. Private review files live
outside this repository. Public phase resolutions belong in docs/REVIEW_LOG.md.

Status handoff locations (relative to this repository root):
- Claude: ../ndpl-private/CLAUDE_PLAN_REVIEW.md
- Gemini: ../ndpl-private/GEMINI_PLAN_REVIEW.md
- Codex: docs/HANDOFF.md and docs/REVIEW_LOG.md

Reviewers put their latest phase, verdict, checks/results, blockers, and next action
at the top of their own canonical file, retaining dated history below. Their final chat
response can simply say which file was updated. The owner need only tell Codex
"Check the review files"; Codex reads both reviewers' current status and reconciles it.
Each agent owns its review file; Codex must not rewrite reviewer verdicts.
Claude writes tests from the approved contracts before reading Codex's implementation.
Keep test-authoring results and code-review findings separate in the canonical review.
Gemini updates its existing canonical review; historical test assignments do not transfer
Claude's current test ownership. Neither reviewer edits the other's files.

Each handoff records files changed, checks and independent test results, assumptions,
limitations, safety/methodology impact and open decisions. Local checks do not substitute
for independent tests or actual measurements. No subagents unless explicitly requested.

Never fabricate results, treat fixtures as measurements, overwrite raw evidence, retune
thresholds against held-out evaluation, or publish without explicit authorization.
