# Limitations

- Phase 2 software was accepted with 198 tests and green Python 3.12/3.14 Linux CI.
  Telemetry, faults, recovery and diagnosis remain unimplemented. The offline GUI is
  implemented, awaiting final review. Claude owns existing tests; Gemini provides a second
  independent methodology and GUI review alongside Claude's broader review.
- Follow-up audit found child signal-mask inheritance and verification consistency/error
  mapping gaps; corrections now pass all 49 independent audit regressions. See HANDOFF.md
  for the remaining fixture correction and review gate. No runner hardware pilot has run.
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
