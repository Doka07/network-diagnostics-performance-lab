# LinkedIn draft — engineering milestone

Status: reviewed software-milestone draft awaiting Denis's publication approval. Not posted. The results-export
feature and corrected preview have independent code and methodology approval. Use a screenshot
that keeps its synthetic-data banner visible. Do not add benchmark figures from fixtures.

---

I’ve been building a Python lab for investigating TCP performance between an Ubuntu PC
and a Windows mini-PC.

The current milestone is an offline desktop inspector: open a saved experiment, inspect
receiver goodput and per-flow smoothed TCP RTT, and trace a value back to its source JSON and checksum.
A saved-run report generator brings those results into a standalone HTML report.

The interesting work has been making the evidence trustworthy:

• Receiver goodput and sender throughput stay separate.
• Warm-up intervals stay separate from retained data—even when iperf3 restarts its clock.
• A measured zero stays zero. Missing data stays unavailable.
• Failed and interrupted runs remain inspectable, with their failure reasons visible.
• Artifact integrity, traffic success and experiment eligibility are shown independently.

One code-review finding was especially useful: a child process inherited blocked termination
signals from its parent. Fixing the startup and cleanup path mattered just as much as drawing
the charts.

The tool is tested locally on Python 3.12 and 3.14. The screenshots use synthetic data;
I’m not presenting them as benchmark results. Hardware diagnostics are underway; a
retained baseline and telemetry correlation remain future work.

Code: https://github.com/Doka07/network-diagnostics-performance-lab

#Python #Networking #Linux #SystemsEngineering #PerformanceEngineering
