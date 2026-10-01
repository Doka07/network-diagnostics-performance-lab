# Architecture

Phase 1 implements an offline path:

```text
CLI -> strict YAML loader -> immutable ExperimentConfig
                         -> bundled JSON Schema + semantic validation
                         -> planned manifest -> exclusive durable artifact write
```

The future controller will coordinate traffic, collectors, injectors, artifacts and analysis
through the protocols in `diaglab/contracts.py`. It runs unprivileged; a separately reviewed
root-owned helper will implement only approved typed fault operations.

Metrics use one batch per collection epoch, with a flat logical view for consumers.
Configuration and batch values are detached and frozen to prevent caller mutation.
Analyzer views contain measured features only and exclude controller ground truth.

Collectors will use separate bounded fast and slow lanes, one outstanding call per
collector, actual process deadlines for command collectors, and a bounded writer queue.
Scheduler wake slip is distinct from collection duration. A Python thread timeout is
not cancellation; noncooperative in-process collection must fail/contain the run.

Windows telemetry will use a campaign/session identity and explicit offset/uncertainty
measurements. The status/time endpoint remains an optional proposed component pending its
own detailed security review. Unknown alignment disables cross-host time overlays.

Schemas are packaged inside diaglab to work in installed wheels without a source checkout.
This refines the preliminary repository layout without changing serialized contracts.
