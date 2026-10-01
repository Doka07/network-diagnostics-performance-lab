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
