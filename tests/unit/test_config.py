"""Independent unit tests for TC-U-01 and TC-U-02.

TC-U-01: Config Schema & Parser (strict YAML, safe defaults, rejection of duplicate keys,
         unsafe tags, anchors, nonfinite floats, unknown fields, cadence limits).
TC-U-02: Safety Preflight Logic (RFC 1918 validation, interface allowlist check,
         rejection of public, multicast, broadcast, and loopback targets).
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

from diaglab.config import ExperimentConfig, load_config
from diaglab.exceptions import ConfigValidationError, MissingInputError

# ==============================================================================
# TC-U-01: Config Schema & Parser Tests
# ==============================================================================


def test_tc_u_01_valid_config_loading(valid_config_file: Path) -> None:
    """TC-U-01: Load a compliant YAML configuration and verify parsed structure."""
    config = load_config(valid_config_file)
    assert isinstance(config, ExperimentConfig)
    data = config.to_dict()
    assert data["schema_version"] == "1.0"
    assert data["campaign_id"] == "c-test-001"
    assert data["evidence_kind"] == "pilot"
    assert data["target"]["host"] == "10.0.0.23"
    assert data["target"]["port"] == 5201
    assert data["target"]["interface"] == "enp12s0"
    assert data["traffic"]["tool"] == "iperf3"
    assert data["traffic"]["duration_s"] == 30
    assert config.sha256 is not None
    assert len(config.sha256) == 64


def test_tc_u_01_safe_defaults_applied(tmp_path: Path, valid_config_dict: dict[str, Any]) -> None:
    """TC-U-01: Verify safe default values are applied when optional fields are omitted."""
    # Remove fields that should have default values
    valid_config_dict["safety"].pop("allow_default_route", None)
    valid_config_dict["safety"].pop("dry_run", None)
    valid_config_dict["safety"].pop("approved_profile_id", None)
    valid_config_dict["traffic"].pop("omit_s", None)

    cfg_file = tmp_path / "defaults.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    config = load_config(cfg_file)
    data = config.to_dict()

    assert data["safety"]["allow_default_route"] is False
    assert data["safety"]["dry_run"] is True
    assert data["safety"]["approved_profile_id"] is None
    assert data["traffic"]["omit_s"] == 0


def test_tc_u_01_reject_duplicate_yaml_keys(tmp_path: Path) -> None:
    """TC-U-01: Strict YAML parsing must reject duplicate keys at any mapping level."""
    raw_yaml = """
schema_version: "1.0"
campaign_id: "c-dup-01"
evidence_kind: "pilot"
target:
  host: "10.0.0.23"
  port: 5201
  interface: "enp12s0"
target:
  host: "10.0.0.24"
  port: 5201
  interface: "enp12s0"
traffic:
  tool: "iperf3"
  protocol: "tcp"
  duration_s: 30
  streams: 1
telemetry:
  collectors:
    - name: "proc_net_dev"
      required: true
      cadence_hz: 10.0
      timeout_s: 0.05
safety:
  allowlist_interfaces: ["enp12s0"]
scenario:
  kind: "baseline"
"""
    cfg_file = tmp_path / "dup_key.yaml"
    cfg_file.write_text(raw_yaml, encoding="utf-8")

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "duplicate" in str(exc_info.value).lower()


def test_tc_u_01_reject_unsafe_yaml_tags(tmp_path: Path) -> None:
    """TC-U-01: Must reject explicit YAML tags like !python/object or !!binary."""
    raw_yaml = """
schema_version: "1.0"
campaign_id: !custom "c-tag-01"
evidence_kind: "pilot"
target:
  host: "10.0.0.23"
  port: 5201
  interface: "enp12s0"
traffic:
  tool: "iperf3"
  protocol: "tcp"
  duration_s: 30
  streams: 1
telemetry:
  collectors:
    - name: "proc_net_dev"
      required: true
      cadence_hz: 10.0
      timeout_s: 0.05
safety:
  allowlist_interfaces: ["enp12s0"]
scenario:
  kind: "baseline"
"""
    cfg_file = tmp_path / "unsafe_tag.yaml"
    cfg_file.write_text(raw_yaml, encoding="utf-8")

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "tags" in str(exc_info.value).lower() or "unsupported" in str(exc_info.value).lower()


def test_tc_u_01_reject_yaml_anchors_and_aliases(tmp_path: Path) -> None:
    """TC-U-01: Must reject YAML anchors and aliases to prevent alias expansion attacks."""
    raw_yaml = """
schema_version: "1.0"
campaign_id: &camp_id "c-anchor-01"
evidence_kind: "pilot"
target:
  host: "10.0.0.23"
  port: 5201
  interface: "enp12s0"
traffic:
  tool: "iperf3"
  protocol: "tcp"
  duration_s: 30
  streams: 1
telemetry:
  collectors:
    - name: "proc_net_dev"
      required: true
      cadence_hz: 10.0
      timeout_s: 0.05
safety:
  allowlist_interfaces: ["enp12s0"]
scenario:
  kind: "baseline"
description: *camp_id
"""
    cfg_file = tmp_path / "anchor.yaml"
    cfg_file.write_text(raw_yaml, encoding="utf-8")

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "aliases" in str(exc_info.value).lower() or "anchors" in str(exc_info.value).lower()


@pytest.mark.parametrize("nonfinite", [".nan", ".inf", "-.inf"])
def test_tc_u_01_reject_nonfinite_floats(tmp_path: Path, nonfinite: str) -> None:
    """TC-U-01: Must reject NaN, Inf, and -Inf in numeric configuration fields."""
    raw_yaml = f"""
schema_version: "1.0"
campaign_id: "c-nonfinite-01"
evidence_kind: "pilot"
target:
  host: "10.0.0.23"
  port: 5201
  interface: "enp12s0"
traffic:
  tool: "iperf3"
  protocol: "tcp"
  duration_s: {nonfinite}
  streams: 1
telemetry:
  collectors:
    - name: "proc_net_dev"
      required: true
      cadence_hz: 10.0
      timeout_s: 0.05
safety:
  allowlist_interfaces: ["enp12s0"]
scenario:
  kind: "baseline"
"""
    cfg_file = tmp_path / f"nonfinite_{nonfinite}.yaml"
    cfg_file.write_text(raw_yaml, encoding="utf-8")

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "nonfinite" in str(exc_info.value).lower() or "invalid" in str(exc_info.value).lower()


def test_tc_u_01_reject_unknown_top_level_key(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-01: Must reject configuration containing unknown/unsupported keys."""
    valid_config_dict["unexpected_rogue_key"] = "malicious_payload"
    cfg_file = tmp_path / "unknown_key.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert (
        "unexpected_rogue_key" in str(exc_info.value) or "additional" in str(exc_info.value).lower()
    )


def test_tc_u_01_reject_duplicate_collectors(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-01: Reject duplicate collector names in telemetry collector list."""
    valid_config_dict["telemetry"]["collectors"].append(
        {
            "name": "proc_net_dev",
            "required": True,
            "cadence_hz": 10.0,
            "timeout_s": 0.05,
        }
    )
    cfg_file = tmp_path / "dup_collector.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "duplicate collector" in str(exc_info.value).lower()


def test_tc_u_01_reject_unknown_collector(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-01: Reject unknown collector names not registered in capability limits."""
    valid_config_dict["telemetry"]["collectors"].append(
        {
            "name": "unsupported_collector_xyz",
            "required": True,
            "cadence_hz": 1.0,
            "timeout_s": 0.5,
        }
    )
    cfg_file = tmp_path / "unknown_collector.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "unknown collector" in str(exc_info.value).lower()


def test_tc_u_01_reject_excessive_collector_cadence(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-01: Reject collector configured with cadence exceeding its maximum safe capability."""
    # tc_qdisc maximum safe cadence is 1.0 Hz in Phase 1 contracts
    for col in valid_config_dict["telemetry"]["collectors"]:
        if col["name"] == "tc_qdisc":
            col["cadence_hz"] = 50.0  # Excessive for subprocess collector
            break
    cfg_file = tmp_path / "excessive_cadence.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "exceeds maximum safe cadence" in str(exc_info.value).lower()


def test_tc_u_01_reject_omit_s_greater_than_or_equal_duration(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-01: traffic.omit_s must be strictly less than traffic.duration_s."""
    valid_config_dict["traffic"]["duration_s"] = 10
    valid_config_dict["traffic"]["omit_s"] = 10
    cfg_file = tmp_path / "invalid_omit.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "omit_s" in str(exc_info.value).lower()


def test_tc_u_01_reject_invalid_evidence_kind(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-01: evidence_kind must be one of 'pilot', 'measured', or 'synthetic'."""
    valid_config_dict["evidence_kind"] = "unverified_production"
    cfg_file = tmp_path / "bad_evidence_kind.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "evidence_kind" in str(exc_info.value).lower() or "enum" in str(exc_info.value).lower()


def test_tc_u_01_reject_oversized_config(tmp_path: Path) -> None:
    """TC-U-01: Configuration files exceeding 1 MiB must be rejected immediately."""
    cfg_file = tmp_path / "oversized.yaml"
    # Write slightly more than 1 MiB of comments
    with cfg_file.open("w", encoding="utf-8") as f:
        f.write("# " + ("A" * 1024) + "\n")
        f.write("# " * 1024 * 1024)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "exceeds 1 mib" in str(exc_info.value).lower()


def test_tc_u_01_missing_config_file_raises_missing_input_error(tmp_path: Path) -> None:
    """TC-U-01: Nonexistent file raises MissingInputError (exit code 2)."""
    nonexistent = tmp_path / "does_not_exist.yaml"
    with pytest.raises(MissingInputError) as exc_info:
        load_config(nonexistent)
    assert exc_info.value.exit_code == 2


# ==============================================================================
# TC-U-02: Safety Preflight Logic Tests
# ==============================================================================


@pytest.mark.parametrize(
    "invalid_ip",
    [
        "8.8.8.8",  # Public IPv4 (Google DNS)
        "1.1.1.1",  # Public IPv4 (Cloudflare)
        "127.0.0.1",  # Loopback
        "224.0.0.1",  # Multicast
        "255.255.255.255",  # Broadcast
        "0.0.0.0",  # Wildcard / all interfaces
        "169.254.1.1",  # Link-local APIPA
        "not_an_ip_address",  # Malformed string
        "10.0.0.1/24",  # CIDR notation
    ],
)
def test_tc_u_02_reject_non_rfc1918_target_host(
    tmp_path: Path, valid_config_dict: dict[str, Any], invalid_ip: str
) -> None:
    """TC-U-02: target.host must be a literal private RFC 1918 IPv4 unicast address."""
    valid_config_dict["target"]["host"] = invalid_ip
    cfg_file = tmp_path / "invalid_host.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "host" in str(exc_info.value).lower() or "rfc1918" in str(exc_info.value).lower()


@pytest.mark.parametrize(
    "valid_rfc1918_ip",
    [
        "10.0.0.1",
        "10.255.255.254",
        "172.16.0.1",
        "172.31.255.254",
        "192.168.1.1",
        "192.168.254.254",
    ],
)
def test_tc_u_02_accept_valid_rfc1918_targets(
    tmp_path: Path, valid_config_dict: dict[str, Any], valid_rfc1918_ip: str
) -> None:
    """TC-U-02: Validate that standard RFC 1918 private ranges are accepted."""
    valid_config_dict["target"]["host"] = valid_rfc1918_ip
    cfg_file = tmp_path / "valid_rfc1918.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    config = load_config(cfg_file)
    assert config.to_dict()["target"]["host"] == valid_rfc1918_ip


def test_tc_u_02_reject_interface_not_in_allowlist(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-02: target.interface must be explicitly included in safety.allowlist_interfaces."""
    valid_config_dict["target"]["interface"] = "eth99"
    valid_config_dict["safety"]["allowlist_interfaces"] = ["enp12s0", "wlan0"]
    cfg_file = tmp_path / "interface_not_allowed.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "allowlist" in str(exc_info.value).lower()


def test_tc_u_02_reject_empty_allowlist_interfaces(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-02: safety.allowlist_interfaces must not be empty."""
    valid_config_dict["safety"]["allowlist_interfaces"] = []
    cfg_file = tmp_path / "empty_allowlist.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "allowlist" in str(exc_info.value).lower() or "minitems" in str(exc_info.value).lower()


@pytest.mark.parametrize("invalid_port", [0, -1, 65536, 70000])
def test_tc_u_02_reject_invalid_port_range(
    tmp_path: Path, valid_config_dict: dict[str, Any], invalid_port: int
) -> None:
    """TC-U-02: target.port must be an integer between 1 and 65535."""
    valid_config_dict["target"]["port"] = invalid_port
    cfg_file = tmp_path / "invalid_port.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "port" in str(exc_info.value).lower()


# ==============================================================================
# IMPL-B-1: Strict YAML Numeric Resolution Regressions
# ==============================================================================


@pytest.mark.parametrize(
    ("field_path", "non_json_num"),
    [
        ("target.port", "010"),  # Octal with leading zero
        ("target.port", "0777"),  # Octal
        ("target.port", "0x10"),  # Hexadecimal
        ("target.port", "0x5201"),  # Hexadecimal
        ("traffic.duration_s", "1_000"),  # Underscore in integer
        ("traffic.duration_s", "12:34"),  # Sexagesimal / time string
        ("traffic.duration_s", "190:20:30"),  # Sexagesimal
    ],
)
def test_tc_u_01_reject_non_json_numeric_formats(
    tmp_path: Path, field_path: str, non_json_num: str
) -> None:
    """TC-U-01 / IMPL-B-1: StrictLoader rejects non-JSON numeric formats (octal/hex/sexagesimal)."""
    # Create valid YAML text and substitute target field with non_json_num representation
    raw_yaml = f"""
schema_version: "1.0"
campaign_id: "c-strict-num-01"
evidence_kind: "pilot"
target:
  host: "10.0.0.23"
  port: {non_json_num if field_path == "target.port" else 5201}
  interface: "enp12s0"
traffic:
  tool: "iperf3"
  protocol: "tcp"
  duration_s: {non_json_num if field_path == "traffic.duration_s" else 30}
  streams: 1
  omit_s: 0
  connect_timeout_s: 10
  finish_timeout_s: 10
  terminate_grace_s: 2
telemetry:
  collectors:
    - name: "proc_net_dev"
      required: true
      cadence_hz: 10.0
      timeout_s: 0.05
safety:
  allowlist_interfaces: ["enp12s0"]
scenario:
  kind: "baseline"
"""
    cfg_file = tmp_path / "strict_num.yaml"
    cfg_file.write_text(raw_yaml, encoding="utf-8")

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    err = str(exc_info.value).lower()
    # Non-JSON numbers resolve as strings and fail the schema integer/number type check
    assert "integer" in err or "number" in err or "type" in err


def test_tc_u_01_accept_strict_json_numeric_formats(tmp_path: Path) -> None:
    """TC-U-01 / IMPL-B-1: StrictLoader accepts strict JSON numeric formats."""
    raw_yaml = """
schema_version: "1.0"
campaign_id: "c-strict-json-num"
evidence_kind: "pilot"
target:
  host: "10.0.0.23"
  port: 5201
  interface: "enp12s0"
traffic:
  tool: "iperf3"
  protocol: "tcp"
  duration_s: 30
  streams: 1
  omit_s: 0
  connect_timeout_s: 10
  finish_timeout_s: 10
  terminate_grace_s: 2
telemetry:
  collectors:
    - name: "proc_net_dev"
      required: true
      cadence_hz: 10.0
      timeout_s: 0.05
    - name: "proc_stat"
      required: true
      cadence_hz: 1e1
      timeout_s: 5e-2
safety:
  allowlist_interfaces: ["enp12s0"]
scenario:
  kind: "baseline"
"""
    cfg_file = tmp_path / "json_num.yaml"
    cfg_file.write_text(raw_yaml, encoding="utf-8")

    config = load_config(cfg_file)
    data = config.to_dict()
    assert data["target"]["port"] == 5201
    assert data["traffic"]["duration_s"] == 30
    assert data["telemetry"]["collectors"][1]["cadence_hz"] == 10.0
    assert data["telemetry"]["collectors"][1]["timeout_s"] == 0.05


# ==============================================================================
# IMPL-B-4: Actionable Scenario-Specific Schema Reporting Regressions
# ==============================================================================


@pytest.mark.parametrize(
    ("scenario_dict", "expected_missing_field"),
    [
        ({"kind": "loss", "limit_packets": 1000}, "loss_pct"),
        ({"kind": "loss", "loss_pct": 5.0}, "limit_packets"),
        (
            {"kind": "latency", "jitter_ms": 1.0, "limit_packets": 1000},
            "delay_ms",
        ),
        (
            {"kind": "latency", "delay_ms": 10.0, "limit_packets": 1000},
            "jitter_ms",
        ),
        (
            {"kind": "latency", "delay_ms": 10.0, "jitter_ms": 1.0},
            "limit_packets",
        ),
        (
            {"kind": "rate", "burst_bytes": 1000, "limit_bytes": 1000},
            "rate_mbit",
        ),
        (
            {"kind": "cpu", "core_id": 0, "duration_s": 5.0},
            "workers",
        ),
    ],
)
def test_tc_u_01_actionable_scenario_missing_fields(
    tmp_path: Path,
    valid_config_dict: dict[str, Any],
    scenario_dict: dict[str, Any],
    expected_missing_field: str,
) -> None:
    """TC-U-01 / IMPL-B-4: Schema errors report specific missing fields, not generic unions."""
    valid_config_dict["scenario"] = scenario_dict
    cfg_file = tmp_path / "scenario_missing.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    err = str(exc_info.value)
    # Must report the specific scenario missing property, not a generic oneOf error
    assert expected_missing_field in err
    assert "scenario" in err


# ==============================================================================
# Non-dry-run Safety Profile ID Requirement
# ==============================================================================


def test_tc_u_02_require_approved_profile_when_dry_run_false(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-02: safety.approved_profile_id is required when dry_run is false."""
    valid_config_dict["safety"]["dry_run"] = False
    valid_config_dict["safety"]["approved_profile_id"] = None

    cfg_file = tmp_path / "non_dry_run_no_profile.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    with pytest.raises(ConfigValidationError) as exc_info:
        load_config(cfg_file)
    assert "approved_profile_id is required when dry_run is false" in str(exc_info.value)

    # Supplying approved_profile_id satisfies the requirement
    valid_config_dict["safety"]["approved_profile_id"] = "profile-p1-safe"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)

    config = load_config(cfg_file)
    assert config.to_dict()["safety"]["dry_run"] is False
    assert config.to_dict()["safety"]["approved_profile_id"] == "profile-p1-safe"
