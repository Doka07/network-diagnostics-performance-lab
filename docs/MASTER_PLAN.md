# Public implementation roadmap

Build a reproducible Ubuntu-client/Windows-receiver TCP diagnostics lab. Collect workload,
transport, queue, NIC and CPU observations and report transparent root-cause hints with
supporting evidence, contradicting evidence and uncertainty. Measure collection overhead.

## Phases

Product interface requirement: a polished Python desktop GUI inspired by Wireshark's
inspection workflow. Proposed staged delivery is in [GUI_PLAN.md](GUI_PLAN.md), starting
with an offline run browser after Phase 2 acceptance. GUI scope needs independent review.

0. Inventory both hosts, confirm topology and perform an approved bounded manual transfer.
1. Establish strict configuration/data contracts, offline CLI, manifests, interfaces and CI.
2. Implement the traffic runner and one/four-stream baseline pilots.
3. Add Linux counters, process overhead and bounded multi-rate collection.
4. Implement reviewed constrained fault application and independently verified recovery.
5. Add Windows telemetry and an explicitly reviewed cross-host alignment mechanism.
6. Develop diagnostic rules with fixtures and separate pilot runs only.
7. Freeze cadence/rules/thresholds from pilots and collect retained overhead comparisons.
E. Collect fresh held-out individual-scenario evaluation under the frozen settings.
8. Evaluate one mixed fault without claiming validated cause ranking.
9. Review evidence, reproducibility, charts and public claims before publication.

Phase 1 is accepted after independent reviews, passing tests, and successful remote CI.
Phase 2 software is also accepted with 198 tests and green Python 3.12/3.14 CI; its
hardware pilots are still pending. GUI steps 1–2 are authorized. Subsequent audit findings
are tracked as corrective work in HANDOFF.md, not erased by prior acceptance.
The authorized bounded manual transfer completed and cleanup was verified. Remaining
host inventory, physical topology confirmation, and subsequent phase gates remain pending.
This readiness sample does not establish a retained performance baseline.

## Evidence rules

The default campaign has one warm-up and seven retained 30-second runs per approved
scenario/control. Each run is the experimental unit; intra-run samples are time series.
The project owner freezes methodology, numeric thresholds and acceptance decisions.

Loss, latency and rate/queue limits are the initial faults. CPU contention requires a
repeatable pilot before entering the validated ruleset. Keep raw data/checksums, preserve
failed runs, report misclassifications and inconclusive outcomes, and use new evaluation
data after any rule retuning. Fixtures never become benchmark evidence.

All live faults require reviewed recovery on the actual host. Existing qdisc configurations
must be supported and restored structurally. Router/switch settings are outside v1 scope.

This project validates a small conventional TCP/Ethernet testbed. It makes no measured
claims about RDMA/RoCE, InfiniBand, production clusters, or vendor-specific fabrics.
