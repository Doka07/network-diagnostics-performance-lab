# Network Diagnostics and Performance Lab

A two-host TCP/Ethernet lab for repeatable experiments and evidence-based performance
diagnostics. The controller is Ubuntu; the receiver is a Windows mini-PC on the same LAN.

The project compares workload, TCP, queue, NIC, and CPU observations to distinguish
possible causes of lower throughput. It will also measure its own collection overhead.

Current stage: Phase 2 software accepted after 198 tests passed on Python 3.12/3.14 CI.
The offline desktop viewer and follow-up runner/verification fixes are implemented.
Claude's final review is approved; see the handoff for remaining reviewer/owner/CI gates. A private manual
readiness transfer was verified; no retained performance campaign or validated diagnosis
is available yet.

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

Phase 2 also supports offline planning and integrity verification:

```bash
.venv/bin/diaglab run --config configs/baseline.yaml --output /tmp/diaglab-run-plan
.venv/bin/diaglab verify --run /tmp/diaglab-run-plan
```

Live baseline traffic requires explicit `--execute`, an approved pilot configuration and
a persistent manually started receiver. See the runbook before execution. Collectors,
fault application, diagnosis and reporting remain later phases.

## Offline desktop viewer

Install the optional GUI on Linux and open a saved run:

```bash
.venv/bin/python -m pip install -e '.[dev,gui]'
.venv/bin/diaglab-gui
```

The viewer provides dark/light themes, interval charts, searchable flow tables and raw
evidence links. It does not start traffic or modify evidence. See the
[preview gallery](docs/mockups/index.html) for screenshots using explicitly synthetic data.
Claude and Gemini approved the GUI and results release, including the corrected preview.
Owner acceptance and updated remote CI remain release gates.
See the [desktop viewer guide](docs/GUI_GUIDE.md) for statuses, controls and evidence links.

## Saved-run results report

Generate an offline HTML/JSON report from explicitly selected saved runs:

```bash
.venv/bin/diaglab results --run /path/to/run-one --run /path/to/run-two --output /tmp/diaglab-report
```

Open `/tmp/diaglab-report/report.html` in a browser. The output must be absent or empty
and separate from all source runs. The report keeps evidence classes and verification
statuses visible, omits source paths/host identities/raw logs, and never pools runs or
marks performance claims accepted. See [results contracts](docs/RESULTS_CONTRACTS.md).
Results reporting has independent code and methodology approval.

## Data and review

- [Command and data contracts](docs/CONTRACTS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Public roadmap](docs/MASTER_PLAN.md)
- [Safety requirements](docs/SAFETY.md)
- [Execution runbook](docs/RUNBOOK.md)
- [Current handoff](docs/HANDOFF.md)

Claude authors independent tests and reviews architecture, code, safety, methodology,
arithmetic, charts and interpretation. Gemini provides a second independent methodology
and GUI review; Claude retains existing test ownership.
The project owner accepts phase results and authorizes experiments and
publication. The CI workflow intentionally requires actual tests; an empty test suite
does not pass the phase gate.

This home-lab project measures conventional TCP/Ethernet. RDMA/RoCE, InfiniBand, data-center
fabric behavior, and production-scale root-cause accuracy are outside the measured scope.
