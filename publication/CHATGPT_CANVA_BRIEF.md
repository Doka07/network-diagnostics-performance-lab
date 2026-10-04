# ChatGPT + Canva handoff: DiagLab

Updated for Denis Krutskih on 2026-10-04. This is a factual briefing, not a final post.
Denis will write/design the final publication with ChatGPT and Canva and approve it himself.
Nothing in this document authorizes publishing. Local paths are navigation aids for Denis;
ChatGPT cannot access them unless the corresponding files are uploaded.

## Start here: instructions to ChatGPT

Help me turn this engineering project into a clear, credible LinkedIn post and a Canva
visual. Use only facts in this briefing. Ask about my preferred voice or visual format if
needed. The strongest story is trustworthy diagnostic evidence and handling real failures,
not a speed record. Write in first person, with concrete engineering details and no hype.
Credit AI-assisted implementation and independent reviews honestly if discussing workflow.
Do not imply I manually authored every line or that every new change has fresh independent
approval. Do not invent a relationship with NVIDIA, deployment at a company, customer
impact, production scale, accuracy statistics, or performance improvements.

Produce:

1. Two post directions: an engineering-story post and a concise project-demo post.
2. A recommended final draft of roughly 150–220 words after I choose a direction.
3. A Canva outline: one hero image or a short carousel, with exact labels and captions.
4. A list of any claims that need further evidence rather than filling gaps with guesses.

Use “pilot” whenever quoting the measurements. If the post is stronger without numeric
results, feature the actual GUI and engineering lessons instead. My objective includes
networking/systems interview preparation; do not turn that into a vendor endorsement.

## Project identity and delivered scope

**Name:** Network Diagnostics and Performance Lab; desktop tool branded **DiagLab**.
**Repository:** https://github.com/Doka07/network-diagnostics-performance-lab
**Verified release commit:** `45404309ef3965cf07f784f941259c384fdfc5d8`.
**Successful CI:** https://github.com/Doka07/network-diagnostics-performance-lab/actions/runs/37139253231

A Python project for reproducible TCP experiments between an Ubuntu sender and a Windows
mini-PC receiver, with a Linux desktop inspector for saved runs and an HTML/JSON results
exporter. The GUI is an offline evidence browser, inspired by network-analysis workflows.
It is not a packet sniffer or a Wireshark replacement.

Delivered capabilities:

- Strict YAML/schema validation and explicit live-run preflight.
- Bounded one/four-stream TCP pilot execution through iperf3.
- Run manifests, raw artifacts, hashes and explicit failure records.
- Owned child-process cleanup, scoped temporary Windows receiver firewall rules,
  independent cleanup verification and receiver evidence capture.
- Finalization that continues after failed checks, records partial output/timing and
  attempts checksums last; operator failures stay separate from traffic failures.
- Dark/light PySide6 desktop GUI: receiver-goodput timeline, per-flow TCP RTT and
  retransmission table, raw JSON, event log and source-evidence links.
- Standalone HTML/JSON reports for explicitly selected saved runs, without pooling them.
- Separate artifact-integrity, traffic-completion and evaluation-eligibility statuses.

Not delivered: packet capture, live GUI experiment controls, cross-host telemetry
correlation, fault injection, automated root-cause diagnosis, a retained benchmark
campaign, overhead studies, held-out accuracy evaluation, RDMA/RoCE or InfiniBand testing.
This is the completed software and bounded-pilot milestone, not the entire roadmap.

## Validation: use these counts precisely

- At committed release **45404309**, **564 test cases passed locally on Python 3.12.3** (100.83 seconds).
- At that same commit, **564 cases passed locally on Python 3.14.8** (96.55 seconds).
- Claude subsequently added **17 independent parallel-interval regressions** and reports
  **581 passed on each runtime** (3.12.3: 97.7 s; 3.14.8: 95.7 s). These additions await
  Denis's commit/push and fresh CI. Do not attribute 581 cases to the older CI run.
- Codex independently reran all **581 cases on Python 3.12.3 on 2026-10-04**:
  **581 passed in 100.63 seconds**, Qt required, no skips. Ruff lint and formatting
  passed (85 files). Today's Python 3.14 result remains attributed to Claude.
- Qt was required (`NDPL_REQUIRE_GUI=1`, offscreen rendering); those full local runs had
  no skipped cases. This is 564 cases exercised on two runtimes, not 1,128 distinct cases.
- Lint, formatting and wheel/source-distribution builds passed.
- Four GitHub Actions jobs passed for commit `45404309`: offline-checks (3.12),
  offline-checks (3.14), gui-checks (3.12), gui-checks (3.14).
- CI jobs have different scopes; do not claim that each of the four ran all 564 cases.
- Claude authored independent tests, including 77 lifecycle/finalization cases.
  Claude independently reviewed and approved the finalizer, lifecycle timing, operator
  and parser on 2026-10-03, with no blocking findings. The 17 new parser regressions
  reproduce the original four-stream failure. Gemini separately reviewed pilot arithmetic
  and the publication briefing, approving its claims with pilot labels and screenshot
  redactions. Neither reviewer authorizes publication on Denis's behalf.

## Successful hardware pilot results

Two separate forward TCP pilots, **one observation per stream-count condition**. Requested
duration 30 seconds, no omitted warm-up, no injected faults, receiver Ethernet negotiated
at 1 Gbit/s. Ubuntu iperf3 3.16; Windows iperf3 3.21 (Cygwin). The Ubuntu NIC negotiated
at 10 Gbit/s; this does not make the two-host path a 10 Gbit/s measurement.

| Measurement | One TCP stream | Four parallel TCP streams |
|---|---:|---:|
| Receiver bytes | 3,530,686,464 B | 3,531,079,680 B |
| Receiver duration | 30.004312 s | 30.009372 s |
| Receiver goodput | **941.381 Mbit/s** | **941.327 Mbit/s** |
| Convenient rounded display | **941.38 Mbit/s** | **941.33 Mbit/s** |
| Sender throughput, separate metric | 941.834 Mbit/s | 943.016 Mbit/s |
| Sender retransmits | 0 | 152 |
| Sender minus receiver byte residual | 1,310,720 B | 5,373,952 B |
| Client reporting epochs | 30 | 30 |
| Zero-byte aggregate epochs | 0 | 0 |
| Zero-window client flow samples | 0 | 0 |
| Traffic completed / result verified | Yes / Yes | Yes / Yes |
| Lifecycle errors | None | None |
| Temporary receiver resources absent after run | Verified | Verified |

Goodput = `8 × receiver bytes / receiver duration`; Mbit/s uses decimal 1,000,000 bps.
Receiver values come from embedded server JSON, not the sender's byte total.
The four-stream figure is an aggregate across four flows, **not per stream**.
The end timestamps include receiver drain; do not replace them with exactly 30 seconds.

These two results are exploratory pilots, not repeated retained measurements. No confidence
interval, speedup, optimal stream count or causal comparison is supported. Do not make a
bar chart implying that the tiny difference between 941.38 and 941.33 is meaningful.
Retransmissions are observed sender counters, not packet-loss percentages. Zero recorded
retransmissions does not prove that no packet was ever lost. Endpoint byte residual is
not packet loss or evidence locating bytes in a particular buffer.

### Optional technical appendix: RTT

RTT below is the sender's per-flow **smoothed TCP RTT**, not packet latency samples or
p95/p99 percentiles. Do not combine flows into a claimed latency distribution.

| Run / flow socket | Mean RTT (µs) | Minimum RTT (µs) | Maximum RTT (µs) | Retransmits |
|---|---:|---:|---:|---:|
| One-stream / 5 | 1,944 | 1,874 | 2,052 | 0 |
| Four-stream / 5 | 7,624 | 6,276 | 8,469 | 27 |
| Four-stream / 7 | 7,627 | 6,598 | 8,476 | 36 |
| Four-stream / 9 | 7,643 | 6,461 | 8,440 | 27 |
| Four-stream / 11 | 7,792 | 6,681 | 8,359 | 62 |

Quality flags remain visible: `REPORTED_DURATION_MISMATCH`, `SENDER_FLAG_MISMATCH`, and
for the four-stream record `PARALLEL_INTERVAL_WINDOWS_DIFFER`. These describe preserved
iperf redundancy/timing issues; they were not erased to make the report look clean.

## The engineering story, including failures

1. **Termination safety.** Codex's audit found inherited blocked termination signals
   in a traffic child. Startup/cleanup was corrected without using `preexec_fn`; Claude's
   independent tests reproduced the issue and cover ordinary termination and escalation.
2. **Failure evidence matters.** Initial real runs stalled and hit the execution deadline.
   Their artifacts remain inspectable; integrity verification does not turn them into
   successful traffic measurements.
3. **Completion is not healthy traffic.** One diagnostic exited successfully while many
   intervals transferred zero bytes. It was not used as a clean pilot or retained result.
4. **Controlled experiments.** A 20-second start delay shifted the observed stall earlier
   within the transfer. Removing a receiver-duration flag did not fix the pause. A no-probe
   attempt never reached traffic; it is not evidence for or against the probe hypothesis.
5. **Windows operating state.** SSH became unreliable. Windows system logs subsequently
   showed repeated Modern Standby entries due to idle timeout. AC sleep was disabled and
   sshd restarted. Clean one/four-stream pilots followed. Both conditions changed, so we
   have not isolated a single definitive root cause for every earlier failure.
6. **A real parser edge case.** Four-stream iperf output samples each flow separately but
   reports aggregate intervals using the first flow's clock. Microsecond differences
   exposed an over-strict parser check. The fix preserves reported totals and actual flow
   windows, flags differing windows and retains byte/order/overlap validation. No numeric
   tolerance was widened and no raw evidence was edited.
7. **Finalization under failure.** Per-run scripts initially skipped reports or checksums
   after an exception. A repository-owned finalizer now attempts every post-run check and
   seals last, without rewriting the original traffic/lifecycle outcome.

A useful takeaway: “A successful exit code, a valid artifact and a healthy experiment
are three different things.” This is an engineering lesson, not an automated diagnostic
capability claim.

## Canva visual brief

Recommended: a real application screenshot with a short engineering-story caption.
Suggested title: **A Python TCP lab built around traceable evidence**.
Suggested supporting labels: **Offline inspector · Source-linked metrics · Failure records**.
If pilot numbers are shown, place **Single 30 s pilot per condition — not a retained benchmark**
next to them, with **Mbit/s** visible. Use **~941 Mbit/s receiver goodput** as a compact label.

Optional five-slide carousel:

1. The real GUI and one-sentence project purpose.
2. Workflow: Ubuntu sender → Windows receiver → saved artifacts → offline inspection.
3. Three separate statuses: integrity / traffic outcome / evaluation eligibility.
4. One concrete lesson: a completed process can still contain prolonged zero-byte intervals.
5. Tests, green CI, repository link and a concise note on next milestones.

Use actual charts/screenshots for measurements. Do not redraw a prettier measured curve,
remove warnings, imply statistical significance or create fabricated dashboard values.
If an existing mockup is used instead, retain its prominent **synthetic data** label.
Real pilot screenshots should be labelled **real pilot data**, not synthetic. Crop or
redact local usernames, file paths and LAN endpoint addresses before public use, without
hiding substantive quality flags, eligibility or failure status. Denis approves the final
visual. Do not use NVIDIA branding or imply affiliation.

## Public links for ChatGPT and the final post

- [Project repository](https://github.com/Doka07/network-diagnostics-performance-lab)
- [Reviewed software commit](https://github.com/Doka07/network-diagnostics-performance-lab/commit/45404309ef3965cf07f784f941259c384fdfc5d8)
- [Passed CI for that commit](https://github.com/Doka07/network-diagnostics-performance-lab/actions/runs/37139253231)
- [Latest GitHub Actions runs](https://github.com/Doka07/network-diagnostics-performance-lab/actions)
- [GUI user guide](https://github.com/Doka07/network-diagnostics-performance-lab/blob/main/docs/GUI_GUIDE.md)
- [Hardware experiment notes and limitations](https://github.com/Doka07/network-diagnostics-performance-lab/blob/main/docs/HARDWARE_DIAGNOSTICS.md)
- [This briefing on GitHub, after Denis pushes it](https://github.com/Doka07/network-diagnostics-performance-lab/blob/main/publication/CHATGPT_CANVA_BRIEF.md)

Upload this Markdown file directly to ChatGPT; it contains the numeric results even
without access to local artifacts. The raw runs, HTML report and original screenshot
are local, not publicly hosted by these links. Supply a redacted real screenshot
separately if asking ChatGPT to critique the Canva visual. Main-branch links may change;
the commit and CI links above identify the tested software precisely.

## Known limits from final review

The supplied-aggregate parser flags differing flow windows but currently accepts any
positive overlap if its byte and first-flow-window checks pass. A tighter maximum skew
is a future contract amendment, not an implemented guarantee. Observed pilot boundary
skew was at most 9 µs client-side and 2 µs server-side; this does not validate arbitrary
large skew. The checkout-only Windows orchestration script is code-reviewed but has no
direct automated end-to-end operator tests; runner, parser, lifecycle and finalizer have
independent coverage. The power-condition label records the known operator-supplied
setup, not a fresh power-state measurement on each run. If SHA256SUMS is absent, do not
infer a sealed bundle from operator-status.json alone.

No endpoint-byte difference establishes where bytes resided or why they were unreceived.
No evidence here proves a particular socket-buffer size caused RTT changes. The post
must not promote speculative reviewer explanations into measured conclusions.

## Local source map and reproducibility

Repository root: `/home/denis/Desktop/network-diagnostics-performance-lab`.
These paths are private/local navigation aids, not assets to post or commit automatically.

- Combined report: `artifacts/post-power-pilot-results-20261003/report.html`.
- Machine-readable report: same directory, `summary.json`; hashes in `checksums.json`.
- One-stream run: `artifacts/windows-control-4104eb0b804745bb840885dc090befd8/run-1`.
- Four-stream run: `artifacts/windows-control-9cc2360685894c3abcb5c0c38e6f5245/run-1`.
- Real GUI screenshot captured from the running application:
  `artifacts/gui-demo-20261003.png` (contains local path and LAN addresses; review before sharing).
- Synthetic gallery: `docs/mockups/index.html` (illustrative, not real measurements).
- Earlier failed attempts and exact limitations: `docs/HARDWARE_DIAGNOSTICS.md`.
- Existing draft as optional inspiration: `publication/LINKEDIN_POST.md`.
- Public claims ledger: `publication/CLAIMS.md`.

Goodput evidence pointer for each successful run:
`client.json#/server_output_json/end/sum_received`, using `bytes`, `start` and `end`.
Client JSON SHA-256:

- One-stream: `2c474a292ff0b9c973272397381473db2275bfdf8a70004970bf5517c418ff30`.
- Four-stream: `89e615980d37e8428d77382739aeb5463896b9b8114fcfb57c80fec38f0f516a`.

Codex rechecked both complete pilot bundles and the report checksums while preparing
this briefing. The one-stream outer bundle has 50 files; the final four-stream bundle
has 53. Earlier rejected/failed evidence remains preserved separately. No new traffic
was run for this briefing. Windows is disconnected and is not needed for inspection.

## Two-minute tool walkthrough

Open the actual GUI on the four-stream run using the command below. It should show **Verified snapshot**,
**Traffic: completed**, **Eligibility: pending**, and approximately **941.327 Mbit/s**.
Pending eligibility is expected for a pilot; it is not a loading error.

1. Click the underlined **Receiver goodput** value. The right pane shows its source JSON,
   pointer and digest. The number comes from receiver bytes and receiver duration.
2. On **Timeline**, use the series dropdown for aggregate receiver goodput or available
   flow/RTT series. Click a plotted interval for evidence; wheel zooms, double-click resets.
3. The lower table shows four flows, their smoothed RTT values and retransmits. Click a
   numeric column header to sort or use the filter box to find a flow/socket/quality flag.
4. Click `client.json` under **Run evidence** to inspect the original text; **Raw evidence**
   provides paging. **Event log** shows execution events. **Collectors** identifies coverage;
   it does not imply that future collectors are implemented.
5. Use **Open run…** / **Ctrl+O** to switch to the one-stream run directory above. Select the
   directory containing `manifest.json`, not its parent operator directory.
6. Use the top-right **Dark/Light** selector. Everything in this inspector is read-only.

Reopen later:

```bash
cd ~/Desktop/network-diagnostics-performance-lab
.venv/bin/diaglab-gui --run artifacts/windows-control-9cc2360685894c3abcb5c0c38e6f5245/run-1
xdg-open artifacts/post-power-pilot-results-20261003/report.html
```

Export new saved-run reports through the CLI (`diaglab results`), not through a GUI export
button. The output directory must be new or empty. No Windows connection is needed.
