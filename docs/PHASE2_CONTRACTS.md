# Phase 2 runner and parser contracts

Current role update: Claude owns independent tests, methodology/arithmetic/chart review
and code review for all phases. Gemini references below describe historical contract work;
its canonical file is retained read-only. Phase 2 software has been accepted by Denis.

Status: both agents approved these contracts and the owner authorized Phase 2 implementation
on 2026-10-01. Implementation is available for independent tests and code review. Additional
hardware traffic has not been authorized. Gemini owns executable independent tests; the
owner alone commits/pushes and authorizes hardware pilots. This document is updated in place.

## Scope

Ubuntu controller, IPv4 TCP, baseline scenario, one or four forward streams, manually
started persistent receiver. No Windows server automation, SSH, firewall management,
faults, telemetry scheduler, diagnosis, reverse/bidirectional transfer, or public claims
in the runner. Receiver startup/firewall are runbook steps outside the Python tool.
Phase 2 results are pilot evidence with diagnostic coverage explicitly absent.

## Parser API: diaglab.traffic.parser

```python
def goodput_bps(bytes_count: int, duration_s: float) -> float: ...
def rate_matches(reported_bps: float, computed_bps: float) -> bool: ...
def parse_iperf3(
    client_json: str,
    *,
    expected_streams: int,
    omit_s: float = 0.0,
    server_json: str | None = None,
) -> Iperf3Report: ...
```

Parser functions are pure: no subprocess, file access, sockets, or host queries.
Parse strict JSON with duplicate-key/nonfinite rejection. Maximum UTF-8 size per document
is 16 MiB; enforce before decoding. `expected_streams` must be integer 1 or 4; omit is a
finite nonnegative number. Baseline forward TCP only: validate test_start.protocol TCP,
reverse false, num_streams matching the expected count, and configured omit metadata.
Unsupported/missing protocol metadata is a named rejection, not an assumed TCP run.
IPv4 socket identities and stream IDs are retained for subsequent runner identity checks.

Return immutable dataclasses in this module (tuples for collections):

| Type | Fields |
|---|---|
| EndpointTotal | bytes_count: int; start_s, end_s, duration_s, computed_bps: float; reported_bps, reported_seconds: float or None; source: str; quality_flags: tuple[str, ...] |
| FlowSummary | socket_id: int; local_host, remote_host: str; local_port, remote_port: int; sender, receiver: EndpointTotal or None; retransmits: int or None; mean_rtt_us, min_rtt_us, max_rtt_us: float or None; rtt_unavailability_reason: str or None |
| TrafficInterval | start_s, end_s, duration_s: float; socket_id: int or None; direction: str; bytes_count: int; computed_bps: float; reported_bps: float or None; omitted: bool; rtt_us, rttvar_us: float or None; source: str |
| Iperf3Report | sender, receiver: EndpointTotal; flows: tuple[FlowSummary, ...]; intervals: tuple[TrafficInterval, ...]; sender_retransmits: int or None; endpoint_byte_residual: int; quality_flags: tuple[str, ...]; receiver_source: str |

Directions are `sent` and `received`, sources `client`, `embedded_server`, `independent_server`.
These are Direction and Source StrEnum values. `Iperf3Report.to_dict()` returns the strict
JSON representation used in traffic_summary.schema.json, with tuple fields as arrays.
VerificationResult also has state, transfer_completed and result_verified, defaulting to
unknown/false for older callers.
Aggregate intervals have socket_id None; flow intervals carry their unique socket ID.
Intervals include omitted entries for inspection but exclude them from retained arithmetic.
No CPU field is normalized or interpreted by this parser; raw output retains native values.

### Direction and source precedence

Determine direction from sum_sent/sum_received and sender/receiver object names under
streams, never from the redundant boolean `sender`. Conflicting booleans add
SENDER_FLAG_MISMATCH without changing direction. Socket tuples and configured endpoint
identify the forward flow; reverse or contradictory endpoint identities are rejected.
Use client-local sending observations for sender metrics and RTT.

Receiver source priority: explicit independent server document, embedded
server_output_json, client receiver summary. Embedded and explicit server documents must
be valid and agree when both exist; a malformed supplied server document cannot be ignored
in favor of another source. Client/server receiver bytes agree exactly; durations and
rates are compared with the redundant-field tolerances below. Differences are recorded
as RECEIVER_SOURCE_MISMATCH, with no silent averaging. A report with that flag is not
eligible even as a successfully reconciled Phase 2 pilot.
Missing server JSON permits a parser result using client receiver data with
SERVER_OUTPUT_UNAVAILABLE. The live runner always requests server output and treats its
absence as a failed verification, preserving the report and raw output.

### Arithmetic and consistency

For each interval/total, authoritative duration is end_s - start_s, strictly positive.
Bytes are exact nonnegative integers (booleans/floating integers are rejected).
Compute `8 * bytes_count / duration_s`; reject negative/nonfinite numeric input and any
overflow producing a nonfinite result. A zero-byte positive-duration interval is valid.
Reported rate consistency: abs(reported - computed) <= max(1 bps, 1e-6 * abs(computed)).
Reported seconds consistency: abs(seconds - duration) <= max(1e-6 s, 1e-6 * abs(duration)).
These are serialization checks, not performance thresholds. Mismatch flags are
REPORTED_RATE_MISMATCH and REPORTED_DURATION_MISMATCH; preserve all values and continue
parsing. Missing redundant fields add REPORTED_RATE_UNAVAILABLE or
REPORTED_DURATION_UNAVAILABLE. No mismatch is silently corrected in raw evidence.

Never sum an aggregate record together with its component flows. Prefer complete aggregate
totals, validating their bytes against the unique flow totals when both are present.
Duplicate socket IDs, missing expected flows, incomplete totals, or inconsistent flow byte
sums raise a named parse error. Derive an aggregate from flows only when all expected flows
cover the same interval/window; otherwise flag WINDOW_MISMATCH and reject reconciliation.
Whole-window interval rate is 8 * sum(retained bytes) / sum(nonoverlapping retained
durations), not an unweighted mean of interval rates or a sum of rates across time.
Parallel streams add bytes over a common wall-time window, not their durations.
For a supplied interval `sum`, iperf uses the first stream's timestamps even though
other streams have independently sampled boundaries. Preserve each flow's actual window
and the supplied aggregate's window; validate exact aggregate byte totals and require
the aggregate window to match the first flow. Differing component windows must share a
positive overlap and add `PARALLEL_INTERVAL_WINDOWS_DIFFER`; they are not silently aligned.
Without a supplied aggregate, differing windows still fail with WINDOW_MISMATCH. This
distinguishes reported aggregation from deriving a new aggregate; numerical serialization
tolerances above are unchanged. Source: [iperf 3.16 interval reporter](https://github.com/esnet/iperf/blob/3.16/src/iperf_api.c#L3381).
Return aggregate and per-flow intervals separately. Validate interval ordering and reject
overlap within a series; arbitrary gaps add INTERVAL_GAP and are not filled with zeros.

Use iperf3's `omitted` indicators and declared omit metadata; never trim a fixed first/last
window. With omit_s zero all non-omitted observed intervals are retained. With omit_s
positive, absence/inconsistency of omission metadata is OMIT_METADATA_MISMATCH; no guess
at steady-state trimming. Do not impose a 30-second summary endpoint: receiver drain can
make the measured window slightly longer than the configured transfer time.

endpoint_byte_residual = sender.bytes_count - receiver.bytes_count, preserved as a signed
integer. This difference is not packet loss and is not proof of a particular buffer state.
Zero reported retransmissions does not establish zero packet loss. RTT is per-flow TCP
smoothed RTT in microseconds. Keep source mean/min/max labels; never compute packet p95/p99
or combine flows into a claimed packet RTT distribution. Missing RTT is None with
`TCP_INFO_UNAVAILABLE`; observed zero must be distinguished from missing data.

### Failures

OMIT_METADATA_MISMATCH is a hard failure, never a soft quality flag: reject unsupported
omission metadata as TRAFFIC_OUTPUT_UNSUPPORTED and contradictory interval omission data
as TRAFFIC_OUTPUT_INCONSISTENT. Do not return a guessed retained interval structure.

Malformed/truncated JSON raises TrafficExecutionError with reason_code
TRAFFIC_OUTPUT_INVALID_JSON (do not claim every syntax error proves truncation).
A top-level `error` in any supplied document is explicit failure. Recognize timeout text
as CONNECTION_TIMED_OUT, refusal text as CONNECTION_REFUSED, otherwise IPERF_REPORTED_ERROR.
Keep the original error string in the exception and raw output; text recognition is only
reason classification. Partial valid JSON lacking required result fields uses
TRAFFIC_OUTPUT_INCOMPLETE. Unexpected stream/direction/omit shape uses
TRAFFIC_OUTPUT_UNSUPPORTED. Contradictory flow totals use TRAFFIC_OUTPUT_INCONSISTENT.
Strict numeric violations raise ArtifactIntegrityError. All these exit 3 in the CLI.
TrafficExecutionError keeps its existing code TRAFFIC_FAILED; add reason_code rather than
replacing the Phase 1 symbolic code with test-specific strings.

## Traffic adapter API: diaglab.traffic.runner

```python
class Iperf3TrafficAdapter:
    name = "iperf3"

    def __init__(self, *, executable: str = "iperf3") -> None: ...
    def prepare(self, context: RunContext) -> None: ...
    def start(self, context: RunContext) -> TrafficHandle: ...
    def wait(self, handle: TrafficHandle) -> TrafficResult: ...
    def stop(self, handle: TrafficHandle) -> None: ...
```

Preserve existing RunContext, TrafficHandle and TrafficResult fields. Extend TrafficResult
with defaults: timeout_stage: str or None = None; cleanup_verified: bool = False;
failure_reason: str or None = None. `wait` returns process outcomes, including nonzero
exit/timeout with artifacts; the orchestrator maps these to CLI failures and calls the
parser only for completed zero-exit processes. Cleanup failure raises FaultCleanupError
(existing exit 4), taking priority. Repeated stop/wait of the same owned handle is bounded
and idempotent; unknown handles are refused without signalling any process.

prepare validates executable availability, baseline/forward/pilot scope, local source IP
and interface, direct route to selected target, non-self/unicast target under the actual
interface prefix, and writable secure artifact directory. Bounded read-only `ip -j`
queries are permitted during live preflight; every subprocess has a timeout and output
size bound. No sudo, shell=True, interpolation, or implicit executable downloads.
The selected source IP is resolved from route/interface state and passed via `-B`.
Baseline transfer does not alter the default-route interface: allow_default_route remains
a fault-mutation restriction, not a blanket prohibition on baseline traffic.

### Liveness and receiver setup

A TCP connect-only probe is real network activity, performed only after explicit execution
selection. Its timeout is connect_timeout_s; no payload throughput test is hidden in
preflight. Failure raises SafetyPreflightError with reason SERVER_UNREACHABLE, exit 1.
It proves TCP reachability only, not iperf3 identity or future liveness. Check again through
the actual transfer result; a server dying after the probe is an execution failure.

Important: a separate probe consumes a one-off server's accepted connection. Therefore
Phase 2 requires a manually-started persistent server, NOT `-1`. The runbook must state
that the probe can produce an aborted control-session message and that a persistent
server must return to listening before the real transfer. Automatic tiny throughput
probes are excluded. Tests must cover this one-off incompatibility. SSH-started manual
servers must retain their SSH session until the run ends; the tool does not manage SSH.

### Ownership, subprocess and deadlines

start launches exactly one owned client, start_new_session=True, argument vector including
`-c TARGET -B SOURCE -p PORT -t DURATION -P STREAMS -O OMIT -J --get-server-output
--connect-timeout CEIL_MILLISECONDS`. Streams are 1 or 4. Capture stdout/stderr verbatim
to exclusive 0600 files using bounded, concurrent draining, with 16 MiB stdout/1 MiB stderr
limits. Limit breach ends the run with OUTPUT_LIMIT_EXCEEDED and preserves captured prefix.
An executable override exists for unprivileged mock-binary tests, never in YAML.

Connect budget and finish budget remain separate settings, but legacy iperf3 3.16's -J
output is emitted only at completion. The parent cannot observe the exact protocol-stage
boundary through that stream. Proposed portable behavior: iperf3 enforces its own
connect timeout; parent enforces the conservative total deadline
connect_timeout_s + omit_s + duration_s + finish_timeout_s from process launch.
An external watchdog expiry is EXECUTION_DEADLINE_EXCEEDED, timeout_stage `execution`;
do NOT falsely label it a known finish timeout. A parsed explicit connection timeout uses
timeout_stage `connect`. Separate parent-observed connect/finish transitions would require
an additional observable protocol/capability and a revised compatibility contract.
**Resolved:** both reviewers accepted this legacy-compatible behavior and Gemini revised
TC-I-02 accordingly. No guessed stage transition or silent capability change is accepted.

stop signals only the owned process group: SIGTERM, wait terminate_grace_s, then SIGKILL
if any owned group member remains, followed by a bounded final verification (2 seconds).
Own/reap the direct child; group children cannot generally be waitpid-reaped by their
grandparent without Linux subreaper semantics. Do not promise otherwise. The adapter
requires no surviving owned group members after cleanup, and always reaps its direct
child. Descendants escaping the session are outside iperf3's supported process contract;
mock tests must report them as a limitation rather than assert impossible generic reaping.
Cleanup failure preserves evidence and overrides execution/interruption. SIGINT and
SIGTERM both trigger cleanup; after verified cleanup SIGINT exits 130 and SIGTERM 143.

## CLI/orchestration API

Proposed module diaglab.run:

```python
def run_experiment(
    config: ExperimentConfig,
    output: Path,
    *,
    execute: bool = False,
    run_role: str = "pilot",
    executable: str = "iperf3",
) -> Path: ...
def verify_run(path: Path) -> VerificationResult: ...
```

`diaglab run --config PATH --output DIR [--execute] [--run-role warmup|pilot]`
defaults to offline planning. Without --execute create a planned manifest and command
plan without host commands, sockets, or executable discovery. No hidden live preflight.
With --execute require config safety.dry_run false, non-null approved_profile_id, pilot
evidence, baseline scenario and one/four streams. These flags express intent but do not
authorize hardware experiments by themselves. Refuse measured/synthetic live runs and
evaluation/overhead roles in this initial phase. No CLI executable override.

`diaglab verify --run DIR` is strictly offline: schema/path validation, checksums and
re-parsing/reconciliation of captured output; no rerun, probes, SSH, or cleanup mutation.
Exit 0 when integrity/structure checks pass, including intact failed-run evidence.
Emit JSON including state, transfer_completed and result_verified booleans. An intact
failed artifact is not a successful transfer. Pending planned runs report false booleans.
Missing manifest/file exit 2; integrity/parse inconsistency exit 3; live preflight refusal
exit 1; execution failure exit 3; cleanup failure exit 4; interruption after verified
cleanup exit 130/143. No phase-acceptance/publication decision is made by verify.
This is the combined run/verify exit-code list. Verify itself returns 0, 2 or 3; it does
not perform live preflight or terminate processes and cannot generate those failures.

run owns a new/empty POSIX directory using the existing no-follow/exclusive guards.
Artifacts: manifest.json, config.json, command.json, events.jsonl, client.json,
client.stderr, traffic_summary.json when parsing succeeds, and checksums.json.
Do not fabricate independent server.json/server.stderr: no server process is owned by
Phase 2. Preserve embedded server JSON verbatim inside client.json; an optional derived
server-output.json is labelled extracted, not independent. Independent Windows capture
belongs to the operator/runbook. Fake-executable test artifacts stay synthetic fixtures.
File writes are bounded, flushed/fsynced before digests. Manifest updates are atomic with
directory fsync; secure lock held across the whole run. Never overwrite raw evidence or
reuse an existing run. Cleanup/failure paths finalize whatever evidence is available.

Keep manifest schema 1.0 state transitions planned -> running -> completed/failed/interrupted;
eligibility stays pending/rejected, never accepted. Declared collectors remain listed but
coverage explicitly records unavailability (NOT_IMPLEMENTED_PHASE2); no telemetry fields
claim measurement. Bundled traffic_summary/checksums/run_command schemas and the exact
event record fields below define the implemented serialized form.
Avoid manifest/checksum self-reference: checksums.json covers config, commands, events,
raw outputs and summary; manifest lists those same payload digests plus checksums.json.
No artifact entry hashes manifest.json itself. verify checks exact expected path coverage,
not only whichever entries happen to be listed. Final stdout JSON is bounded and gives
run_id, state, manifest path and result_verified, not a diagnosis.

### Implemented serialized records

- traffic_summary.json: schema_version 1.0 and report, validated by the bundled
  traffic_summary.schema.json; report matches Iperf3Report.to_dict exactly.
- checksums.json: schema_version 1.0 and files (path, size_bytes, sha256), validated by
  checksums.schema.json; paths use the closed Phase 2 payload list.
- command.json: run_command.schema.json requires schema_version, execute, argv, source_ip,
  result_verified, transfer_completed, returncode, timeout_stage and failure_reason.
  Offline argv uses the explicit unresolved `<LIVE_SOURCE_IP>` placeholder. Source, exit
  code, timeout stage and failure reason can be null where no observation exists.
- events.jsonl: records have name, timestamp_utc (Z), monotonic_ns and optional message;
  identical records are embedded in manifest.events. Event names are RUN_PLANNED,
  LIVE_PREFLIGHT_STARTED, LIVE_PREFLIGHT_PASSED, TRAFFIC_STARTED, TRAFFIC_EXITED,
  TRAFFIC_VERIFIED, RUN_FAILED, CLEANUP_VERIFIED and CLEANUP_FAILED.
- manifest collector_coverage has an optional unavailability_reason field, populated with
  NOT_IMPLEMENTED_PHASE2 for every unimplemented collector. Missing counts are not measurements.

CLI run output has run_id, state, manifest and result_verified. Verify output has verified,
state, transfer_completed, result_verified and reasons. Run identity is recorded in
manifest.json. Schemas keep version 1.0; older records remain valid because coverage
reason is optional. Owner acceptance remains outside these commands.

## Reviewer reconciliation and fixtures

Accepted: key-path direction, end-minus-start duration, explicit error handling, receiver
source precedence, liveness check with persistent-server requirement, and captured fixtures.
Private raw evidence is immutable. Gemini may construct scrubbed regression fixtures under
tests/fixtures/iperf3 with documented original digest, scrubbed digest, source/build,
transforms, and test-only provenance. Preserve numeric data and the misleading sender
flags; remove host names, internal IPs, source paths, cookies and timestamps as appropriate.
Use documentation IPv4 ranges in fixtures, permitted by pure parser tests only; live
configuration still requires approved private addresses. Label fixtures captured_regression
and not usable as retained experiment evidence; they are not synthetic fabricated metrics.

Evidence reconciliation for Claude Finding 2: end.sum_received.seconds matches end-start,
but end.streams[0].receiver.seconds differs. Claude narrowed the finding to that per-flow
path in his current review. The parser records REPORTED_DURATION_MISMATCH while preferring
consistent server-side receiver values. Raw source JSON retains the original mismatch.
Gemini's exact "ten unacknowledged blocks"/"no loss occurred" explanation is not established
by the byte difference and zero retransmissions; report the residual without that inference.
CPU percentages remain raw build-specific observations, not normalized host aggregate CPU
or proof of Cygwin overhead. EEE disabled on Ubuntu does not rule out behavior elsewhere
along the physical path. Do not promote those explanations into accepted findings.

Do not edit the old environment.json to refresh status: retain its digest and timestamp.
A new dated inventory snapshot/supplement will record installed versions and the completed
check. Physical path/shared-traffic still needs owner confirmation; do not declare Phase 0
closed. No such unknown fact is filled in by inference from throughput.

Claude/Gemini: update existing canonical review files with explicit contract verdicts and
the timeout/liveness dispositions. Gemini can prepare tests against these named APIs after
those decisions and owner scope authorization; production files remain Codex-owned.
