# Draft claim review

No retained benchmark or performance-improvement claim is accepted. The two recorded
pilot observations may be described explicitly as pilots, one per condition. This ledger supports the software milestone
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
| Python 3.12/3.14 validation | 564 cases per runtime at commit 45404309; green CI run 37139253231. Claude added 17 PX cases and reports 581 passing per runtime | New tests await owner commit and fresh CI; runtime repetitions are not distinct test cases |
| Synthetic previews and real screenshot | docs/mockups has synthetic banners; artifacts/gui-demo-20261003.png shows the real four-stream pilot | Label each accurately; redact paths/endpoints from public screenshot while retaining flags |
| One/four-stream pilot receiver goodput | 941.381 / 941.327 Mbit/s; exact bytes/durations in CHATGPT_CANVA_BRIEF.md, independently checked by Gemini | One 30-second observation per condition; no speedup, statistical significance or retained benchmark claim |
| Hardware baseline and telemetry remain open | docs/MASTER_PLAN.md, docs/HARDWARE_DIAGNOSTICS.md | Diagnostic runs exist but do not establish a retained baseline; telemetry remains future work |

Claude's final 2026-10-03 code review approves the finalizer, lifecycle timing, operator
and parser with no blockers. Gemini's Round 12 independently verifies pilot arithmetic
and approves the briefing subject to pilot labels and screenshot redactions. Some causal
explanations in that review remain stronger than the evidence; they are not adopted:
byte residuals do not locate buffers or prove discard, and neither a buffer-size cause
for RTT nor a single cause for earlier stalls is established.

Denis approves the final ChatGPT/Canva text and visual. See CHATGPT_CANVA_BRIEF.md for the
complete publication handoff and source links. Do not attribute uncommitted additions to
an earlier commit's CI. No claim of automated root-cause diagnosis, packet capture,
RDMA/RoCE, InfiniBand, production scale, validated accuracy, overhead measurement or
measured speedup is supported.
