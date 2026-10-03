# Hardware diagnostic status — 2026-10-03

## Latest: SSH restored and post-change one/four-stream pilots passed

The owner disabled AC sleep (600 s → 0), retained AC hibernation=0 and the High performance
plan, and restarted sshd. Codex independently confirmed hostname, plan and timeouts.
Read-only Windows system events show repeated Modern Standby entries due to Idle Timeout
during the earlier diagnostic period. These support a power-state investigation, not a
claim that every earlier stall had a proven single cause.

One 30 s runner control then completed with the original probe and receiver duration
limit retained, no added delay. All 30 client intervals had nonzero bytes and nonzero send
window. Receiver data: 3,530,686,464 bytes over 30.004312 s, 941.381 Mbit/s. This is a
diagnostic pilot only, not a repeated retained benchmark. Because both sleep policy and
sshd state changed, this does not isolate their individual effects.

Evidence: `artifacts/windows-control-4104eb0b804745bb840885dc090befd8`. Lifecycle had no
errors; process/listener/rule absence, verify and export checks all passed. Repository-owned
finalization sealed 50 files, all hashes checked. The earlier SSH blocker below is historical.

The first post-change four-stream attempt, `windows-control-a2b953288bc942a991c978a255f0d9ca`,
finished its iperf transfer and cleaned up, but the parser rejected parallel interval
boundaries differing by microseconds. The failure remains immutable (49 verified hashes).
The parser now distinguishes a supplied iperf interval aggregate from an aggregate it
derives itself; actual per-flow windows remain unchanged and are flagged when different.
Exact byte reconciliation, first-flow aggregate timing, positive flow overlap, per-series
ordering and strict derivation rules remain enforced. No numeric tolerance was increased.
See PHASE2_CONTRACTS.md for the upstream-source-based clarification and HANDOFF.md for
the fresh-run outcome. This was a software parsing issue, distinct from the earlier stall.

Fresh four-stream evidence: `artifacts/windows-control-9cc2360685894c3abcb5c0c38e6f5245`.
Receiver data: 3,531,079,680 bytes over 30.009372 s, 941.327 Mbit/s. Thirty client epochs,
no zero-byte aggregate epochs and no zero-window flow samples. All four flows are retained
separately; 152 sender retransmits are reported. Known iperf redundancy/timestamp flags
remain visible. Verification, lifecycle and independent absence checks passed; 53 hashes
checked. This is one bounded pilot, not statistical evidence of a performance improvement.

Both requested stream-count pilots now have successful results under the new operating
condition. Combined saved-run report: `artifacts/post-power-pilot-results-20261003/report.html`.
The retained campaign and later project phases remain future work.

The offline GUI, saved-run reporting and traffic runner are implemented. The automated
hardware baseline is not accepted. A completed transfer is distinct from an uninterrupted
transfer, artifact verification, receiver cleanup and a retained performance result.

## Controlled observations

| Condition | Traffic observation | Cleanup / evidence |
|---|---|---|
| Original runner pilot and lifecycle-corrected retry | Both reached the 50 s execution deadline; late intervals show zero send window | Corrected retry had clean lifecycle and verified capture |
| E1: add 20 s after receiver readiness | Actual hold 20.000479233 s; zero window appears at 10–11 s instead of about 29 s; later data burst at 21–22 s; deadline failure | Session and cleanup-command timeouts retained; captured cleanup says all resources gone; independent listener/rule check agrees |
| E2: keep E1 delay, remove only receiver duration limit | CLI completed with verified artifacts, but zero window and no progress persisted after roughly 9–10 s; receiver duration 38.611165 s versus client 30.001640 s | Lifecycle command timeouts retained; subsequent independent check confirms process, listener and rule gone |
| Direct client without TCP probe, original receiver settings | Readiness query timed out before client launch; no traffic test occurred | Lifecycle and evidence capture verified; listener/rule absence confirmed |

E1 supports a relationship to receiver startup or launch context. It does not identify
a timer or establish a precise onset from a long interval containing separated bursts.
E2 does **not** establish a fix: successful termination coexisted with prolonged stalls.
The no-probe hypothesis remains untested. No production probe or receiver flag changed.
No four-stream run occurred and none of these diagnostic records is a retained benchmark.

## Evidence retained locally

Private, ignored evidence directories:

- `artifacts/diagnostic-e1-564f8342b5844f93b509ce1849c0e33a` — 54 checked hashes.
- `artifacts/diagnostic-e2-1a86293ec282450795c9e73071c310d1` — 54 checked hashes.
- `artifacts/diagnostic-no-probe-0016b86f36154089a3a1623bfc5b0f3e` — 38 checked hashes.

E1/E2 include saved-run verification and HTML/JSON exports. Original lifecycle failures
remain immutable even where later checks confirmed cleanup. The E2 private helper copy
has SHA-256 `051967e5e60ced5dfcaf6a349d25058e96fff0e6fa5cd50430107b70efb56697`;
the repository helper remains unchanged at `cea61667…7059`.

## Previous operational limitation (SSH restored above)

Windows SSH subsequently timed out during banner exchange in three bounded attempts.
Ping received two of three replies in one short check; this alone does not diagnose the
transfer issue. A read-only Windows power/event query could not execute. All diagnostic
receivers and temporary rules were verified removed before command access was lost.

When Windows command access returns, first inspect SSH/service health and power/system
events, then complete the no-probe diagnostic with one changed condition. Do not repeat
unmodified traffic or remove production preflight based on an unexecuted experiment.
If local Windows intervention is required, the previously effective recovery command
in administrator PowerShell is `Restart-Service sshd`; no remote restart was performed.

Denis authorized Codex to proceed autonomously without waiting for reviewers. These new
execution observations are Codex's checks, not newly issued independent reviewer verdicts.
