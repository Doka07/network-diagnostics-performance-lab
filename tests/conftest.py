"""Shared test fixtures for independent Phase 1 tests."""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

VALID_CONFIG_DATA: dict[str, Any] = {
    "schema_version": "1.0",
    "campaign_id": "c-test-001",
    "evidence_kind": "pilot",
    "target": {
        "host": "10.0.0.23",
        "port": 5201,
        "interface": "enp12s0",
    },
    "traffic": {
        "tool": "iperf3",
        "protocol": "tcp",
        "duration_s": 30,
        "streams": 1,
        "omit_s": 0,
        "connect_timeout_s": 10,
        "finish_timeout_s": 10,
        "terminate_grace_s": 2,
    },
    "telemetry": {
        "collectors": [
            {
                "name": "proc_net_dev",
                "required": True,
                "cadence_hz": 10.0,
                "timeout_s": 0.05,
            },
            {
                "name": "proc_net_snmp",
                "required": True,
                "cadence_hz": 10.0,
                "timeout_s": 0.05,
            },
            {
                "name": "proc_stat",
                "required": True,
                "cadence_hz": 10.0,
                "timeout_s": 0.05,
            },
            {
                "name": "tc_qdisc",
                "required": True,
                "cadence_hz": 1.0,
                "timeout_s": 1.0,
            },
        ],
    },
    "safety": {
        "allowlist_interfaces": ["enp12s0"],
        "allow_default_route": False,
        "dry_run": True,
        "approved_profile_id": None,
    },
    "scenario": {
        "kind": "baseline",
    },
}

VALID_METRIC_BATCH_DATA: dict[str, Any] = {
    "schema_version": "1.0",
    "run_id": "r-0123456789abcdef0123456789abcdef",
    "campaign_id": "c-test-001",
    "evidence_kind": "synthetic",
    "host_id": "ubuntu-controller",
    "collector": "proc_net_dev",
    "collector_version": "0.1.0",
    "timestamp_utc": "2026-10-01T18:00:00.123456Z",
    "monotonic_ns": 1_000_000_050,
    "sequence": 1,
    "scheduled_monotonic_ns": 1_000_000_000,
    "collection_start_monotonic_ns": 1_000_000_010,
    "collection_end_monotonic_ns": 1_000_000_100,
    "data_quality_flags": [],
    "metrics": [
        {
            "name": "rx_bytes",
            "value": 1048576,
            "unavailability_reason": None,
            "unit": "bytes",
            "scope": "interface",
            "tags": {"interface": "enp12s0"},
        },
        {
            "name": "tx_bytes",
            "value": 2097152,
            "unavailability_reason": None,
            "unit": "bytes",
            "scope": "interface",
            "tags": {"interface": "enp12s0"},
        },
    ],
}


@pytest.fixture
def valid_config_dict() -> dict[str, Any]:
    return copy.deepcopy(VALID_CONFIG_DATA)


@pytest.fixture
def valid_config_file(tmp_path: Path, valid_config_dict: dict[str, Any]) -> Path:
    cfg_file = tmp_path / "valid_config.yaml"
    with cfg_file.open("w", encoding="utf-8") as f:
        yaml.dump(valid_config_dict, f)
    return cfg_file


@pytest.fixture
def valid_metric_batch_dict() -> dict[str, Any]:
    return copy.deepcopy(VALID_METRIC_BATCH_DATA)
