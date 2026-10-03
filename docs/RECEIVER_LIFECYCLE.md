# Receiver lifecycle correction — G2

Status: implementation for independent review; no live execution authorized by this file.
This is operator tooling under scripts/, outside the traffic runner and its CLI. It does
not change measurement settings, install software, or change power/network tuning.

## Local shutdown API

`scripts.receiver_lifecycle.start_session(argv: list[str]) -> Session` starts an owned
POSIX process group, with stdout/stderr continuously drained into bounded buffers
(8 MiB each). The caller supplies an explicit pinned SSH command; no shell interpolation.
`Session` is created by this function, never from an arbitrary PID.

`finish_session(session, *, stop_argv, cleanup_argv, capture_argv, output,
traffic_failure=None, shutdown_timeout=30, command_timeout=60, terminate_grace=2) -> dict`
attempts to reserve a new/empty artifact output before issuing any shutdown command.
If reservation or writing fails, cleanup and capture still run; OUTPUT_UNAVAILABLE or
EVIDENCE_WRITE_FAILED/FINAL_RECORD_WRITE_FAILED is returned explicitly. No persistence
is claimed when the filesystem is unavailable. The operator must check the returned
record and retain it in another safe destination. Each command is an
argument vector. Timeouts must be positive finite numbers. Defaults are seconds.

Always perform these steps, independently catching errors at each step:
1. Request stop with a bounded command.
2. Wait for the owned receiver SSH session. On timeout record SESSION_WAIT_TIMEOUT.
3. Terminate remaining owned local session group with TERM, then KILL only if necessary;
   reap the direct child. Never kill by executable name or an arbitrary PID.
4. Run independent ownership-checked remote cleanup/verification, even if earlier steps
   failed. Its JSON must have exactly process_gone/listener_gone/rule_gone, all boolean true.
5. Attempt receiver evidence capture even if cleanup could not be verified. Missing files,
   invalid JSON/base64, digest/size mismatch and transport failures are explicit failures.
6. Write lifecycle.json and local checksums.json. Preserve traffic_failure verbatim in a
   separate field; lifecycle errors never replace it. This private record may contain paths.

Each command has its own timeout and owned group cleanup. Output overflow is a lifecycle
error; drain/discard beyond the bound so the child cannot deadlock on a full pipe.
The original session's output is also retained. No command failure may skip later steps.
KeyboardInterrupt during shutdown is recorded and cleanup continues. OS kill/power loss
cannot guarantee local evidence; the remote start command has its own 240-second bound.

Returned/persisted keys: schema_version (1.0), traffic_failure (string/null),
lifecycle_errors (list of codes), cleanup_verified (bool), evidence_verified (bool),
local_session_reaped (bool), commands (per-step returncode/timed_out/output_overflow),
missing_files (list), session_wait_s (elapsed wait before local reaping). Each command also
records started_utc and duration_s, including its bounded local cleanup. These LR-8 fields
are additive. Any lifecycle error means lifecycle success is false, even if later
recovery verifies cleanup. There is no success CLI exit or automatic retry.

Capture wire JSON: `{files: {name: base64}, manifest: {files: [{path, size_bytes, sha256}]},
missing_files: [name]}`. Required names are owner.json, server.jsonl, server.stderr,
cleanup.json. Exact closed names; receiver computes SHA-256 after process termination.
Local verifier checks all required entries, exact decoded lengths and hashes before
marking evidence verified. Evidence is saved under receiver- names and never overwrites.
Missing or corrupt evidence still gets a lifecycle record. No invented empty substitutes.
Individually verified files may remain after a later file fails; evidence_verified stays
false. If the final checksums write fails, the returned record adds FINAL_RECORD_WRITE_FAILED
after lifecycle.json was written; the persisted record cannot claim bundle completion.

## Diagnostic finalization (FZ)

`scripts.diagnostic_finalize.finalize_diagnostic(root, *, traffic, operator_failures,
lifecycle, checks, check_timeout=60)` performs ordered post-run command checks regardless
of earlier failures. `traffic` is null or `{started: bool, failure: str|null}`; a failure
without traffic is invalid. Operator failures are uppercase codes, separate from the
verbatim traffic outcome and immutable lifecycle record. Check names match `[a-z0-9_-]+`
and values are nonempty argv lists. Timeouts must be positive finite numbers. Invalid
arguments raise before writes or subprocesses; runtime failures return a failure record.

Each check owns a process group, retains bounded partial stdout/stderr on timeout, and
records UTC start and monotonic elapsed time. Every check is attempted. Output is written
exclusively under `finalization/`; existing seal/status files are never overwritten.
After checks, `operator-status.json` is written, then `SHA256SUMS` covers all regular files
under the root except itself. Symlinks and special files cannot be sealed. A failed seal
returns `sealed=false`; the returned record is authoritative and must be kept separately
if persistence failed. A clean diagnostic denotes successful collection/finalization,
not necessarily successful traffic or baseline eligibility. Recovery uses a new addendum.

`scripts/windows_diagnostic.py --config PATH --known-hosts PATH` is checkout-only operator
tooling for authorized one- or four-stream, 30 s Ubuntu-to-Windows pilots. It pins the existing
host fingerprint, checks copied helper hash/syntax and receiver identity, executes the
normal runner with its TCP probe, then unconditionally attempts lifecycle and finalization.
It does not replace or bypass production preflight. The current condition is explicitly
recorded as post-SSH-restart with AC sleep/hibernation disabled. Root directories are unique.
Power mutations and automatic retries are not provided. A four-stream run requires its
own approved configuration and is not automatically launched after a one-stream run.

## Windows helper details

`scripts/windows_receiver.ps1 -Action Start|Stop|Cleanup|Capture -Token HEX32
-LocalAddress IPV4 -PeerAddress IPV4 -InterfaceAlias NAME -Port 5201`
uses one unique directory under TEMP and one token-named firewall rule. Start refuses
existing directories, rule names or listeners. Preload NetSecurity/NetTCPIP before readiness.
Record executable, process ID and exact creation ticks. Persistent server: never -1.
Creation ticks are serialized as decimal strings. Start persists launch_attempted before
creating the process; incomplete persisted identity after a launch attempt is unverified,
never evidence of process absence. The original process object is retained for cleanup
if a later identity write fails. Capture checks the full identity, not just PID existence.
Capture also refuses the same executable at the recorded PID when ticks differ: this
is an ambiguous identity that could otherwise permit hashing a live receiver's logs.
Ready marker is written only after owned listener verification; no socket probe here.
Start retains the SSH session, waits for a stop marker or 240-second deadline, and runs
cleanup in finally. Importing modules is outside the receiver lifetime deadline.

Stop only creates the stop marker in the existing owned directory. Cleanup validates
process identity (PID, creation ticks, executable) before termination and rule ownership
before removal. Identity mismatch refuses mutation and never signals a replacement process.
Cleanup checks process, listener and rule absence independently and writes cleanup.json.
Capture must refuse hashing live receiver logs. Files remain in the private remote
directory for recovery; nothing is automatically deleted.

## Deployment and no-traffic Windows validation

Copy the exact reviewed helper bytes to a unique private Windows staging directory over
the pinned SSH connection. Compute SHA-256 locally and with Get-FileHash on Windows and
require equality before invoking powershell.exe -NoProfile -File with explicit parameters.
Do not paste a reconstructed script into an encoded command. Start records helper_sha256
in owner.json before starting the receiver; capture preserves this provenance.

After W1/W2 code re-review, validate Start → READY → Stop → Cleanup → Capture with no
iperf client and no connect-only probe. This creates only the scoped temporary receiver
listener/rule. From a separate SSH session, confirm creation-tick strings match the live
process and cleanup identifies it correctly. Confirm all three cleanup booleans and
captured hashes, then independently check listener/rule absence. This validation does
not establish hardware throughput. The 240-second loop is conditional on the wrapper
remaining alive and responsive; it is not an independent watchdog or a guarantee after
SSH teardown/OS termination. Independent recovery remains mandatory when status is unknown.

## Independent review and diagnostic retry

Claude: author a fake-SSH regression that exceeds the wait bound and prove that independent
cleanup and capture still run, traffic failure survives, lifecycle timeout is recorded,
local children are gone and missing evidence is explicit. Also cover nonzero transport,
output overflow, bad hashes, partial cleanup and normal completion. Review Windows
ownership guards separately; offline mocks cannot validate Windows process semantics.
Gemini: review the separation of measurement failure from lifecycle failure and the evidence
rules. Correct the factual discrepancies listed in HANDOFF.md in your canonical review.

After lifecycle approval, propose one diagnostic 30-second single-stream retry, unchanged
iperf versions, host settings and runner budgets, with private before/after inventory.
This isolates lifecycle changes; it does not establish a stall fix. Stop after that run,
preserve all failures and defer four streams. Extra samplers, version substitutions,
interactive startup and power changes require separate reviewed conditions and owner
approval. Existing baseline authorization is not expanded to those interventions.
