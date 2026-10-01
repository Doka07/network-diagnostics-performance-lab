# Limitations

- Phase 1 is an offline implementation. Traffic, telemetry, fault recovery and diagnosis
  are not implemented or validated yet.
- Gemini's updated 134-test suite passes locally on Python 3.12. Claude verified all code
  fixes and the updated test suite; owner acceptance remains pending. Remote CI and
  Windows/Python 3.14 execution are not yet verified.
- Host inventory is incomplete and no throughput readiness check has run.
- Validation enforces offline address/configuration rules; it does not confirm target or
  route identity against live network state.
- Controller secure artifact operations currently require POSIX. Windows agent collection
  and alignment will receive separate review and implementation.
- Raw evidence stays private until a reviewed scrubbed export. Hashes detect alteration
  against trusted references; they do not establish authentic experimental provenance.
- Future conclusions apply to software-impaired TCP/Ethernet in this testbed, without
  RDMA/RoCE, InfiniBand or production-scale validation claims.
