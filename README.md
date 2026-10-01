# Network Diagnostics and Performance Lab

A two-host TCP/Ethernet lab for repeatable experiments and evidence-based performance
diagnostics. The controller is Ubuntu; the receiver is a Windows mini-PC on the same LAN.

The project compares workload, TCP, queue, NIC, and CPU observations to distinguish
possible causes of lower throughput. It will also measure its own collection overhead.

Current stage: Phase 1 code and tests cleared by both reviewers, with 134 tests passing;
remote CI and owner acceptance pending.
No throughput results or validated diagnoses are available yet.

## Getting started

The Ubuntu controller requires Python 3.12 or newer. Create a local environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/diaglab config validate --config configs/baseline.yaml
.venv/bin/diaglab manifest create --config configs/baseline.yaml --output /tmp/diaglab-planned-run
```

`python -m diaglab` and `diaglab` use the same entrypoint. Both commands above are offline.
Manifest creation refuses a nonempty output directory. The manifest records a planned
run with empty observations and pending eligibility; it is not a measurement.

Only configuration validation and planned manifest creation are implemented. Traffic,
collectors, fault application, diagnosis, and reporting remain later phases.

## Data and review

- [Command and data contracts](docs/CONTRACTS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Public roadmap](docs/MASTER_PLAN.md)
- [Safety requirements](docs/SAFETY.md)
- [Execution runbook](docs/RUNBOOK.md)
- [Phase 1 handoff](docs/HANDOFF.md)

Gemini authors independent tests. Claude reviews architecture, code, safety, and
interpretation. The project owner accepts phase results and authorizes experiments and
publication. The CI workflow intentionally requires actual tests; an empty test suite
does not pass the phase gate.

This home-lab project measures conventional TCP/Ethernet. RDMA/RoCE, InfiniBand, data-center
fabric behavior, and production-scale root-cause accuracy are outside the measured scope.
