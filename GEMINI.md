# Gemini independent validation role

Follow AGENTS.md. Author independent tests against docs/CONTRACTS.md and the approved test
matrix. Phase 1 covers configuration, metric round trips, manifest hashes/paths and CLI
exit codes. Keep test IDs stable. Use isolated temporary directories, label synthetic
fixtures and never present them as performance results. Update the existing private
canonical review file in place; do not create per-round files.

Canonical status destination: ../ndpl-private/GEMINI_PLAN_REVIEW.md. Put the latest verdict,
test/check results, blockers and next action first; retain dated history. A short completion
notice pointing to this file is sufficient; the owner does not need to relay the report text.
