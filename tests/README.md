# Independent tests

Gemini owns test authoring under tests/unit and tests/integration against the reviewed
contracts and matrix.

Phase 1 tests authored and passing:
- `TC-U-01` (`tests/unit/test_config.py`): Strict YAML parsing, safe defaults, rejection of duplicate keys, unsafe tags, anchors/aliases, nonfinite floats, unknown fields, and cadence limits.
- `TC-U-02` (`tests/unit/test_config.py`): Safety preflight logic, RFC 1918 IPv4 unicast validation, interface allowlist check, rejection of public, multicast, broadcast, and loopback targets.
- `TC-U-03` (`tests/unit/test_metrics.py`): Metric batch validation, RFC 3339 UTC timestamps, monotonic ordering, duplicate series rejection within an epoch, lossless round trips, flattening, and tag whitelist enforcement.
- `TC-U-04` (`tests/unit/test_manifest.py`): Manifest generator, structure, run ID formatting, SHA-256 calculation, and regular file hashing.
- `TC-U-04B` (`tests/unit/test_manifest.py`): Path traversal (`../`), absolute paths, Windows drive/backslash paths, symlink rejection in paths and roots, mode 0600 file creation, and refusal of populated or symlinked destination directories.
- `TC-I-01` (`tests/integration/test_cli.py`): CLI subcommand execution, exit codes (0, 1, 2), refusal to overwrite populated destinations, symlink refusal, `--version`, and entrypoint consistency.

Later privileged tests require explicit provisioning and approval; they never execute
against the controller's live network from ordinary CI.
