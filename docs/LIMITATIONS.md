# Limitations

- Phase 2 implements baseline pilot traffic and parsing; independent Phase 2 tests and
  code review are pending. Telemetry, faults, recovery and diagnosis remain unimplemented.
- Phase 1 was accepted with 134 independent tests and green Python 3.12/3.14 Linux CI.
  The new runner has not completed remote CI or an authorized hardware pilot.
- A private manual readiness transfer passed. Physical topology, shared traffic and a
  dated inventory supplement remain open; Phase 0 is not fully closed.
- Offline validation does not confirm live route identity. Explicit execution verifies
  the local source and direct route and performs a bounded TCP-connect probe.
- Controller secure artifact operations currently require POSIX. Windows agent collection
  and alignment will receive separate review and implementation.
- The receiver is manually started as a persistent server. No Windows/firewall automation
  is implemented. Buffered iperf3 JSON requires a combined parent execution deadline.
- Cleanup covers the owned process group and reaps its direct child; descendants escaping
  the session are unsupported. Smoothed TCP RTT fields are not packet-level percentiles.
- Raw evidence stays private until a reviewed scrubbed export. Hashes detect alteration
  against trusted references; they do not establish authentic experimental provenance.
- Future conclusions apply to software-impaired TCP/Ethernet in this testbed, without
  RDMA/RoCE, InfiniBand or production-scale validation claims.
