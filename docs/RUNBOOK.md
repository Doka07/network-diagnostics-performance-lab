# Runbook

## Offline Phase 1

```bash
python -m diaglab config validate --config configs/baseline.yaml
python -m diaglab manifest create --config configs/baseline.yaml --output /tmp/diaglab-planned-run
```

Use a new or empty output directory. `manifest.json` records state `planned`, no observations
and pending eligibility. A valid configuration is not a passed live preflight.

## Environment readiness

Record interface/address/route, negotiated link/duplex, NIC/driver/offloads, TCP settings,
queue structure, software build/provenance and clock state on both hosts. Record the actual
physical path and shared traffic. Unsupported queries are explicit.

`scripts/windows_inventory.ps1` provides read-only discovery and saves private artifacts to
an explicitly supplied output directory. Run it manually on the receiver. No remote
execution is assumed. Python and iperf3 discovery can be unavailable independently.

After inventory, present exact installation/firewall/server/traffic commands for the manual
readiness check. This check precedes acceptance of performance readiness. The first public
result campaign requires later implementation, safety review, frozen settings and tests.

## Phase 2 baseline execution

Default `diaglab run --config PATH --output DIR` is offline. `diaglab verify --run DIR`
checks integrity and re-parses recorded summaries without opening network sockets.
Use a new output directory for every run.

Live execution requires a separately authorized pilot configuration: baseline scenario,
one or four streams, evidence_kind pilot, safety.dry_run false and the approved profile ID.
The receiver must be manually started as a persistent iperf3 server, without `-1`.
The runner's connect-only reachability probe can consume a one-shot server connection.
Firewall and receiver setup are operator tasks; the tool does not configure Windows.
After reviewing the concrete configuration, `--execute` selects live execution.

Inspect state, cleanup, transfer_completed and result_verified after execution. An intact
failed run can pass integrity verification. Collectors are unavailable in Phase 2, so
traffic completion cannot establish diagnostic coverage or campaign eligibility.
The tool leaves eligibility pending/rejected. Owner acceptance is recorded separately in
the project handoff; it does not rewrite immutable run evidence to accepted.
