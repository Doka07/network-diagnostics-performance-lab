# Desktop diagnostic interface — proposed scope

Denis requested a polished Python desktop diagnostic tool inspired by Wireshark.
This is a product requirement; implementation scheduling and contracts need independent
review. Phase 2 software is accepted; Denis authorized mockup and offline viewer work.

## Experience

Use a clear, dense workspace with resizable panes, light/dark themes, readable typography,
keyboard navigation and explicit units. Status must use text and icons as well as color.
Borrow the inspection workflow: selecting a run, flow or event reveals its details and
original evidence. Packet capture and Wireshark filter syntax are outside this GUI scope.

Suggested layout:

```text
Open run | Plan experiment | Start approved run | Stop       Search/filter
-----------------------------------------------------------------------
Runs and flows | Timeline and sortable observations | Selected details
               | Goodput, RTT, events               | Source and quality
-----------------------------------------------------------------------
Evidence / Logs / Diagnostics        State | Integrity | Cleanup
```

The first release opens existing run directories, verifies artifacts, displays receiver
goodput and per-flow data, and links values to raw evidence. Show unavailable telemetry,
gaps and quality flags explicitly. Failed and interrupted runs remain inspectable.
Distinguish artifact integrity, traffic completion and experimental eligibility.

Timeline charts support zoom, selection and synchronized detail inspection. Later
collector phases add CPU, retransmissions and queue counters only when measured.
Diagnostic explanations appear after the analyzer exists; absent analysis shows unavailable.

## Proposed architecture

Candidate toolkit: PySide6 (official Qt for Python), with Qt Widgets for the desktop
workspace. Dependency versions, plotting library and packaging await a compatibility
check and reviewer decision. Keep GUI dependencies optional so headless CLI/CI works.

CLI and GUI share parser, validation, artifacts and analysis services. The GUI must not
reimplement formulas or relax execution checks. Verification/loading happens off the UI
thread with bounded progress updates. Traffic ownership and cleanup belong to an isolated
controller worker; window closure/cancellation must not orphan traffic or future faults.
The detailed worker and shutdown contract must precede live GUI controls.

Opening a saved run performs no network operations and never rewrites raw evidence.
Live actions remain explicit, use the existing execution gates and retain owner-approved
scope. Rendering rate is separate from telemetry cadence and must be measured in the
observer-overhead study if the GUI is active during retained runs.

## Delivery sequence

1. Review the scope and a visual mockup with Denis, Claude and Gemini.
2. Implement an offline artifact browser and run/flow inspector after Phase 2 acceptance.
3. Add charts as supported metrics become available; independent UI and data tests.
4. Add reviewed live controls after worker lifecycle/cancellation contracts and tests.
5. Add analyzer explanations, comparison and reviewed export as later phases mature.

Claude reviews architecture, lifecycle, scope, methodology, arithmetic and chart fidelity,
and writes independent tests for values, missing data, filtering, responsiveness and
cancellation. Gemini provides a second independent methodology and GUI review; Claude
retains existing test ownership. Each updates their existing canonical review file.
GUI contracts are in GUI_CONTRACTS.md. GUI work does not close later phase gates.

Toolkit reference: https://doc.qt.io/qtforpython-6/
