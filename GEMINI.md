# Gemini review role — active

Gemini provides a second independent methodology and GUI review. Claude retains existing
test ownership and broader code/safety review. Review arithmetic, chart/source fidelity,
warm-up display, evidence links, missing data and usability. Read docs/HANDOFF.md and
docs/GUI_CONTRACTS.md. Route proposed regressions to Claude; do not edit his tests or
production code unless separately assigned. The test-authoring assignment below is history.

Follow AGENTS.md. Author independent tests against docs/CONTRACTS.md and the approved test
matrix. Phase 1 covers configuration, metric round trips, manifest hashes/paths and CLI
exit codes. Keep test IDs stable. Use isolated temporary directories, label synthetic
fixtures and never present them as performance results. Update the existing private
canonical review file in place; do not create per-round files.

Canonical status destination: ../ndpl-private/GEMINI_PLAN_REVIEW.md. Put the latest verdict,
test/check results, blockers and next action first; retain dated history. A short completion
notice pointing to this file is sufficient; the owner does not need to relay the report text.
