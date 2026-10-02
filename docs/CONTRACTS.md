# Command and data contracts

Phase 2 APIs and CLI behavior are in [PHASE2_CONTRACTS.md](PHASE2_CONTRACTS.md).
Implementation is available for independent testing and code review.

Saved-run results report/export contracts are in [RESULTS_CONTRACTS.md](RESULTS_CONTRACTS.md).
`diaglab results --run DIR [--run DIR ...] --output DIR` explicitly writes a new minimized
HTML/JSON report bundle outside source directories; it does not execute experiments.

The schemas in `diaglab/schemas/` are bundled package resources and the authoritative
serialized field definitions. All seven use JSON Schema draft 2020-12. Python validation
additionally enforces finite JSON values, exact numeric types and semantic constraints.
No schema reference requires network retrieval.

## Implemented commands

| Command | Behavior |
|---|---|
| `diaglab config validate --config PATH` | Offline YAML validation; JSON result on stdout |
| `diaglab manifest create --config PATH --output DIR [--run-role ROLE]` | Write only a new planned manifest in an absent/empty directory |
| `python -m diaglab ...` | Same `diaglab.cli:main` entrypoint as the console script |

`run --config PATH --output DIR` plans offline; `--execute` explicitly selects live
baseline pilot traffic. `verify --run DIR` checks artifacts offline. `recover` and
`analyze` remain unimplemented.

| Exit | Meaning |
|---|---|
| 0 | Success; offline validity does not certify live-host readiness |
| 1 | Invalid configuration or preflight refusal, including nonempty destination |
| 2 | Usage or missing required input |
| 3 | Execution/data-integrity failure |
| 4 | Cleanup failure, prioritized over the triggering failure in later lifecycles |
| 130 | User interruption after successful cleanup |
| 143 | SIGTERM interruption after successful cleanup |

Errors go to stderr as `SYMBOLIC_CODE: explanation`. Argparse usage errors exit 2.
Offline verify uses only exits 0, 2 and 3. Exit 0 can verify an intact failed run;
inspect state, transfer_completed and result_verified separately.

For Phase 2, approved_profile_id identifies the owner's approved baseline traffic setup;
later fault phases use it for the approved fault profile. It is not authorization by itself.

## Configuration

Required root objects: `schema_version: "1.0"`, `campaign_id`, `evidence_kind`, `target`,
`traffic`, `telemetry`, `safety`, `scenario`. Optional `analysis` contains a complete
ruleset/settings hash and threshold/window configuration when supplied.

- Input is at most 1 MiB of UTF-8, safe JSON-compatible YAML. Reject duplicate keys,
  aliases/anchors, explicit tags, unknown fields, non-string keys, nonfinite numbers,
  unsupported schema versions and non-JSON types. Only lowercase `true`/`false` are booleans.
- Never coerce a quoted number, numeric boolean or floating integer into the expected type.
  Implicit numbers use JSON syntax: leading-zero, hex, sexagesimal and underscore forms
  remain strings and fail validation in numeric fields.
- Target host is a literal RFC1918 IPv4 address; port is an integer 1–65535; selected
  interface must occur in its explicit allowlist. Self/broadcast/route/identity checks
  need actual network state and are deferred to live preflight.
- Traffic is TCP/iperf3. Duration, streams and connect/finish/termination budgets must
  be positive. `omit_s` defaults to zero and must be below duration.
- Collector names are unique; cadence and timeout are positive. Declared capability limits
  are initially 50 Hz for direct local readers and 1 Hz for command collectors. These
  are ceilings, not measured guarantees or frozen experiment defaults.
- `allow_default_route` defaults false; `dry_run` defaults true; `approved_profile_id`
  defaults null. A missing safety object is invalid. No YAML flag grants execution authority.
  A non-dry-run configuration requires a non-null approved profile identifier.
- Scenarios use tagged strict objects. Baseline has only `kind`. Loss/latency require an
  explicit packet limit; rate requires explicit rate/burst/byte limit. Initial mixed scope
  is loss plus delay. Validation checks shape/units; approved hardware-specific profiles,
  fault bounds and retained-evaluation eligibility remain later gates.

`load_config(path)` returns an immutable `ExperimentConfig`. `to_dict()` returns an
independent mutable copy; `sha256` hashes normalized canonical UTF-8 JSON including defaults.

## Metrics

`MetricBatch.from_dict(record)` and direct construction validate identical rules.
Every record requires campaign identity, plus a run ID (`r-` plus 32 lowercase hexadecimal
digits) or agent-session identity for continuous receiver collection. It includes evidence kind,
host/collector/version, UTC RFC3339 timestamp ending in Z, host-local monotonic time,
sequence, scheduled/start/end monotonic timestamps, quality flags and a metrics array.
Monotonic observation time must lie between collection start and end.

Each metric has `name`, numeric-or-null `value`, `unit`, `scope`, and scalar-valued `tags`.
Tags are limited to 32 entries, with keys up to 128 and string values up to 256 characters.
Scopes are host, interface, flow, process, core, queue, agent and scheduler. Missing value
requires a nonempty `unavailability_reason`; observed values cannot carry such a reason.
Duplicate series (name, scope, canonical tags) inside one collection epoch are rejected.

`to_json_line()` produces finite canonical JSON plus newline. `from_json_line()` rejects
duplicate JSON keys/nonfinite values. `flatten()` repeats the epoch header with one `metric`
per record. `from_flat_records()` requires identical headers, preserves series order, and
reconstructs an equal batch. Immutable storage is detached from caller-owned dictionaries.

The later writer must have bounded buffering/backpressure, timed and event flushes,
flush/fsync before checksum finalization, and bytes/records-written overhead accounting.
Phase 1 supplies serialization contracts, not the telemetry writer/scheduler.

## Manifests and paths

`planned_manifest(config, *, run_role="pilot")` returns a strict planned record with opaque run ID, build/source
and normalized-config hashes. Observations, artifacts, clock records and sessions are empty;
eligibility is pending; cleanup is not applicable. Unknown settings/profile hashes and
environment/ground-truth references are null. No accepted-result flags are fabricated.

Run role (warmup, pilot, evaluation, overhead) is independent of evidence kind. APIs and
CLI default to pilot for standalone planning; the future orchestrator must supply the actual
role explicitly. Synthetic evidence remains explicitly synthetic regardless of role.

`create_run_manifest(config, output, *, run_role="pilot")` writes `manifest.json` with exclusive creation,
per-directory arbitration and flush/fsync. Existing nonempty destinations, symlinks and
concurrent creators are refused. Failures preserve partial output rather than deleting
evidence. POSIX no-follow directory operations are required for secure controller writes.

`safe_artifact_path(root, relative_path)` rejects absolute, parent-traversal, backslash,
non-normalized and symlink paths. `artifact_digest(root, relative_path)` uses no-follow
directory-relative opens, reads only regular files, detects in-read size/time changes,
and returns path, byte size and SHA-256. Hashes detect later alteration against a trusted
manifest; they are not authentication of experiment origin.

Campaign freeze identity later consists of a common-settings hash plus an approved
per-scenario profile map; run-specific IDs/times/counters are excluded. Different approved
scenarios are not treated as accidental settings drift.

## Boundaries for later phases

`diaglab.contracts` declares collector, traffic, injector, analyzer and privilege-helper
protocols. `diaglab.models` defines contexts, handles/results, capabilities, agent sessions,
clock estimates and fault leases. Cleanup must eventually be bounded and idempotent.
Clock estimates default unknown fields to null and validity to false.

`RunArtifacts` accepts immutable `AnalysisSample` features only. It has no configuration,
ground-truth, paths or command-log fields. Analysis tags use a measured-feature allowlist.
The later importer is responsible for constructing this view; structural exclusion alone
does not replace behavioral label-invariance tests or a frozen held-out evaluation.

The summary schema defines statuses NO_DEGRADATION, SINGLE_HINT, MULTIPLE_CONTRIBUTORS and
INCONCLUSIVE, with evidence, alternatives, limitations, confidence rationale and quality
flags. No calibrated probability/ranking is implied. Analysis execution is a later phase.
