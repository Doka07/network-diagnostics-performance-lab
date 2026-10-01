# Decisions

## 2026-10-01 — Initial implementation scope

The project owner approved starting implementation after independent planning reviews.
Offline Phase 1 proceeds alongside readiness discovery. Host readiness and the manual
throughput check remain incomplete; no runner or live fault is implemented in Phase 1.
Private planning and reviews were moved outside the public repository before scaffolding.

## 2026-10-01 — Implementation refinements

- Use Python 3.12+, stdlib argparse/dataclasses, PyYAML and JSON Schema validation.
- Bundle canonical schemas under diaglab/schemas so installed distributions carry contracts.
- Use strict JSON-compatible YAML without anchors, aliases, explicit tags or merge keys.
- Apply schema plus semantic validation; keep offline and runtime network checks distinct.
- Use a batch-per-epoch artifact model with immutable values and a reversible flat view.
- Use POSIX no-follow opens for the controller's secure manifest/hash operations. The future
  Windows telemetry agent has a separate platform contract.
- Keep future traffic/fault/analyzer commands absent until their assigned phases.
- CI requires Gemini-authored tests; no-tests-collected is not converted into success.

Numeric experiment thresholds, software/build compatibility, Windows agent/endpoint,
privilege-helper installation, fault profiles and publication acceptance remain future
evidence/review decisions. No public software license has been selected yet.
