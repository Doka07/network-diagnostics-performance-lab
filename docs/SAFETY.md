# Safety

Phase 1 can validate configuration and write a planned manifest. It cannot start traffic,
apply faults, install a helper, change routes or change Windows firewall settings.

Before any live fault, later implementation/review must establish:

- Explicit interface/target identity, a root-owned allowlist/profile, bounded parameters,
  noninteractive privilege checks and local or independent management recovery.
- A protected durable fault lease and supported initial qdisc restoration recipe.
- An independent verified expiry before mutation, shared ownership/locking and idempotent
  restoration; expiry is cancelled only after verified success.
- Normal/failure/interruption/SIGKILL tests in an isolated privileged environment before
  supervised hardware validation.
- Structural pre/post comparison of qdisc kinds, handles, parents and parameters;
  dynamic counters are not part of restore equality. A dump alone is not a restore recipe.
- Bounded restoration-verification retries. Failed or unverifiable restoration stops
  the campaign and preserves partial artifacts.

An editable YAML boolean is not authorization. No blanket sudo for tc, systemd-run or the
whole application. Recovery never executes user-writable temporary scripts. Reboot may
clear transient state but persistent services can reapply it; recovery must be verified.

No router/switch configuration changes or uncontrolled traffic in v1. Root shaping affects
the selected interface's control and unrelated traffic too; household activity matters.
