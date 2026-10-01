# Measurement methodology

No retained measurement campaign has run. Configuration defaults are starting values,
not accepted thresholds. Inventory/setup evidence is private until a reviewed export.

- Pilot one and four TCP streams. Choose the campaign workload from pilot evidence.
- Use one warm-up and seven retained 30-second runs per approved configuration/scenario.
  A run is the experimental unit; samples inside it are not independent replicates.
- Preserve raw records and failed/rejected runs. Rejection requires predeclared objective
  integrity/environment/fault/cleanup reasons; poor throughput alone is not a reason.
- Tune rules on pilots. Freeze cadence, settings, methodology and rules before fresh
  held-out evaluation. Retuning needs a new version and fresh evaluation runs.
- Include native and matching qdisc controls to expose queue-structure effects.
  Latency-only trials require zero qdisc-drop delta; CPU scenarios require a repeatable pilot.

For matching endpoint/scope/window: interval rate = 8 * bytes / actual interval duration;
whole-run goodput = 8 * sum(bytes) / sum(durations). Do not double-count streams plus their
aggregate, assume exact nominal durations or force sender bytes to equal receiver bytes.
Use the full non-omitted window initially. No arbitrary slow-start/teardown cropping.

Across runs report median, MAD, range and count. Report TCP smoothed RTT as median/range
with its actual source, without packet-tail percentile claims.

Compare minimally orchestrated traffic with 1 Hz, 10 Hz and fast-only 50 Hz collection.
Throughput disturbance = 100 * (bare median - monitored median) / bare median. Include both
hosts, parent/child collection CPU, RSS, sample misses/jitter and artifact/report cost.

Unknown values remain unavailable; no zero imputation. Numeric acceptance and completeness
thresholds are chosen from pilots and approved before retained comparisons.
