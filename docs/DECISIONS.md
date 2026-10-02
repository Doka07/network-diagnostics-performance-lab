# Decisions

## 2026-10-02 — results reporting and post drafting

Denis requested work on a results tool and final post. Codex's initial interpretation is
an offline saved-run report/export, with a draft describing the implemented software and
engineering lessons. RESULTS_CONTRACTS.md defines this bounded scope. The request does not
turn fixtures into measurements or publish the post. Existing reviewer conversations and
canonical files are the coordination mechanism; replacement sessions are not authorized.

## 2026-10-02 — two active independent reviewers

Denis restored Gemini as the second independent methodology and GUI reviewer. Claude
retains existing independent test ownership and broader review responsibilities. Both
canonical review files are active; prior role assignments below are historical.

## Phase 2 accepted; GUI and standing review assignment

After verified green CI, Denis instructed Codex to go ahead with GUI mockup and offline
viewer work, accepting Phase 2 software. Hardware pilots and live GUI controls remain
separate. Denis confirmed Claude takes over all former Gemini duties for every phase:
independent tests, methodology, arithmetic and chart fidelity, alongside code review.
There is one independent reviewer. Historical Gemini records are retained unchanged.

## 2026-10-01 — Desktop GUI requirement

Denis requested a polished desktop interface inspired by Wireshark. Record it as a
product requirement alongside the reusable Python backend and CLI. GUI_PLAN.md proposes
the workspace and staged delivery. PySide6 is a candidate, not a finalized dependency;
GUI implementation contracts and scope await review. Phase 2 review continues.

## 2026-10-01 — Phase 2 implementation authorized

Both independent reviewers approved PHASE2_CONTRACTS.md. Denis then explicitly instructed
Codex to check both reviews and go ahead. This authorizes baseline runner/parser implementation
and independent testing/review, not additional LAN traffic or later phases. The approved
design requires a persistent manual receiver and a combined parent execution deadline.
Commits and pushes remain owner-only. Phase 2 acceptance awaits implementation reviews.

## 2026-10-01 — Manual readiness transfer

The owner explicitly authorized one bounded 30-second single-stream Ubuntu-to-Windows
transfer and its temporary peer/IP/interface-scoped firewall rule. Codex operated it
over verified SSH. A connection-only attempt failed; the corrected attempt kept the
server's SSH session alive and completed. Both attempts are preserved privately,
successful endpoint results reconcile, and temporary process/firewall cleanup is verified.
No configuration of NICs, qdiscs, TCP settings, routes or persistent firewall rules was
changed. This is readiness evidence only; remaining inventory and subsequent phase gates
still apply. Local documentation changes remain for the owner to commit.
## 2026-10-01 — Phase 1 accepted

The project owner explicitly accepted Phase 1 after both independent reviews and the
successful Python 3.12/3.14 GitHub Actions run. Phase 1 is closed. The accepted tool is
the offline CLI and contracts; live traffic, telemetry, faults, and analysis remain
later deliverables. This acceptance does not authorize unspecified host changes or
live fault injection. Commits and pushes remain the project owner's responsibility.

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
