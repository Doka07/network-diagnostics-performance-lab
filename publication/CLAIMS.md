# Draft claim review

No quantitative performance claim is accepted. This ledger supports the software milestone
draft in LINKEDIN_POST.md. Posting and final wording require Denis's approval.

| Draft statement | Evidence / verification | Status and limit |
|---|---|---|
| Ubuntu/Windows TCP lab | docs/MASTER_PLAN.md, docs/DECISIONS.md; Phase 0 readiness record | Existing setup; no retained campaign claimed |
| Saved-run desktop inspection | diaglab/gui, inspection.py, presentation.py; TG-01–12 | Established Claude and Gemini round 5 approval |
| Receiver goodput, per-flow TCP RTT, source pointers | parser.py, inspection.py; R-3/R-4/R-27, CORE-1/CHART-1/ZERO-1 | Smoothed TCP RTT, not packet latency or tail percentiles |
| HTML saved-run report | diaglab/results.py, CLI results command, RESULTS_CONTRACTS.md | 70 Claude-authored RT cases; Claude and Gemini approve implementation and corrected preview; PREVIEW-1 closed |
| Warm-up separated; zero distinct from missing | CHART-1, SHIFT-1, ZERO-1 and missing-data tests | Report/chart behavior; not experimental conclusions |
| Failed/interrupted evidence and independent statuses | AUD-02/03, FAIL-1; GUI contracts | Checksums detect changes against references, not authentic origin |
| Child signal inheritance finding and correction | AUD-01 regressions, run.py and reviewer history | Reproduced with fake processes; no live performance inference |
| Python 3.12/3.14 local validation | Claude independently reports 483 passed on each runtime; Gemini confirms 483 each | Includes required Qt and 70 RT cases; fresh remote CI pending |
| Screenshots are synthetic | docs/mockups/generate.py, generate_results.py and visible banners | Results preview uses fake-process pilot fixtures with a preview-only synthetic banner; never measurement evidence |
| Hardware experiments/telemetry are next | docs/MASTER_PLAN.md | Future work, not delivered functionality |

Before posting: independent results review and tests must clear; update this ledger to the
tested source revision; complete owner commit/push and fresh CI so the linked repository
contains the described functionality. Verify the screenshot retains its synthetic label.
No claim of automated root-cause diagnosis, packet capture, RDMA/RoCE, InfiniBand, production
scale, validated accuracy, overhead measurement or measured speedup is supported yet.
