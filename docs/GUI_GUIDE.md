# Offline run inspector

DiagLab opens an existing run directory and inspects a fixed, verified snapshot of its
artifacts. It does not capture packets, start experiments or modify the selected run.
The desktop viewer currently runs on Linux/POSIX. The Windows PC remains the receiver.

## Install and open

From the repository directory with Python 3.12 or newer:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[gui]'
.venv/bin/diaglab-gui
```

Use **Open run…** or **Ctrl+O** and enter the run directory containing `manifest.json`.
You can also supply it on launch:

```bash
.venv/bin/diaglab-gui --run /path/to/saved-run
```

Opening a large run happens in a background worker. **Cancel loading** or **Escape**
cancels that read. Choosing another run replaces the pending selection. Closing the
window waits for the loader to stop; it does not stop an external experiment.

## Read the three statuses separately

| Indicator | Meaning |
|---|---|
| Verified snapshot | Captured artifacts pass checksums, schema and consistency checks. This is not proof of measurement authenticity. |
| Traffic status | Planned, completed, failed or interrupted. A verified snapshot may describe a failed transfer; its reason remains visible. |
| Eligibility | Pending or rejected under the current pilot workflow. Verification never marks a run accepted as benchmark evidence. |

Unfinalized and integrity-failed runs retain readable raw artifacts but suppress numeric
results and charts. The details pane explains the issue. A repaired or newly finalized
directory must be reopened; displayed values never silently update under an existing view.

## Inspect values and sources

- The headline goodput uses the receiver result. Sender throughput is labeled separately.
- Select an interval series from the timeline menu. Wheel to zoom; double-click to reset.
  Click an interval to see its raw value, source artifact, JSON pointer and SHA-256.
- Warm-up intervals are shaded before retained time when iperf3 restarts its clock.
  The details pane shows both display and raw JSON timestamps. Warm-up is excluded from
  retained totals. Gaps and unavailable samples are not bridged.
- Click headline values or metric cells for their evidence. If a reference could not be
  resolved, the details pane says it is unavailable; verification status is unchanged.
- RTT columns are smoothed TCP RTT in microseconds, not packet-latency percentiles.
  Missing metrics show **Unavailable**; the full reason is in the tooltip and details.
- Filter flows by literal address, port, socket ID or quality flag. Click metric headers
  to sort their numeric values; unavailable values stay last. Resize or scroll the flow
  table horizontally when needed.
- Select an artifact in **Run evidence** to inspect paged raw text and digest information.
  **Event log** and **Collectors** distinguish recorded events from unimplemented telemetry.

Dark and Light themes are available in the top-right menu. Theme selection and the Open
dialog do not save preferences or recent-path history.

## Preview without measurements

[The local preview gallery](mockups/index.html) contains seven screenshots with explicitly
synthetic data. Values are invented and must not be quoted as performance results.
To regenerate these illustrations, install development dependencies and run:

```bash
.venv/bin/python -m pip install -e '.[dev,gui]'
QT_QPA_PLATFORM=offscreen .venv/bin/python docs/mockups/generate.py
```

This development script uses fake local processes with network preflight hooks replaced.
It writes the seven preview images and temporary synthetic artifacts; the viewer itself
remains read-only. It adds the documented synthetic banner for the screenshots.

## Current limits

This release candidate is an offline inspector, with no live controls, telemetry collectors,
fault injection, automated diagnosis, comparison or export. The testbed has no retained
performance campaign yet. See [the current handoff](HANDOFF.md) for independent reviews,
validation versions and remaining phase/CI gates.
