"""Independent integration tests for TC-I-01.

TC-I-01: CLI Subcommand Interface & Exit Codes
- diaglab config validate --config PATH
  - Exit 0: valid config; prints JSON with status="valid"
  - Exit 1: invalid schema or refused preflight; prints symbolic code to stderr
  - Exit 2: missing input file or CLI usage error
- diaglab manifest create --config PATH --output DIR
  - Exit 0: planned manifest created in new/empty directory
  - Exit 1: refused when destination is populated or contains symlinked ancestor
  - Exit 2: missing required arguments
- Entrypoint consistency between python -m diaglab and console script.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml


def run_diaglab_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Execute diaglab CLI via 'python3 -m diaglab' as a child subprocess."""
    env = os.environ.copy()
    env["PYTHONPATH"] = "." + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "diaglab", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


# ==============================================================================
# TC-I-01: diaglab config validate tests
# ==============================================================================


def test_tc_i_01_config_validate_success(valid_config_file: Path) -> None:
    """TC-I-01: config validate exits 0 and prints JSON status for a valid configuration."""
    result = run_diaglab_cli(["config", "validate", "--config", str(valid_config_file)])
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "valid"
    assert payload["schema_version"] == "1.0"
    assert len(payload["config_sha256"]) == 64
    assert payload["live_preflight_performed"] is False


def test_tc_i_01_config_validate_schema_error_exit_1(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-I-01: config validate exits 1 on schema violation with symbolic code on stderr."""
    valid_config_dict["schema_version"] = "99.0"  # Invalid schema version
    bad_cfg = tmp_path / "bad_schema.yaml"
    bad_cfg.write_text(yaml.dump(valid_config_dict), encoding="utf-8")

    result = run_diaglab_cli(["config", "validate", "--config", str(bad_cfg)])
    assert result.returncode == 1
    assert "CONFIG_INVALID" in result.stderr


def test_tc_i_01_config_validate_preflight_refusal_exit_1(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-I-01: config validate exits 1 when preflight safety rules are violated."""
    valid_config_dict["target"]["host"] = "8.8.8.8"  # Public IP rejected by preflight
    bad_cfg = tmp_path / "bad_ip.yaml"
    bad_cfg.write_text(yaml.dump(valid_config_dict), encoding="utf-8")

    result = run_diaglab_cli(["config", "validate", "--config", str(bad_cfg)])
    assert result.returncode == 1
    assert "CONFIG_INVALID" in result.stderr or "PREFLIGHT_REFUSED" in result.stderr


def test_tc_i_01_config_validate_missing_file_exit_2(tmp_path: Path) -> None:
    """TC-I-01: config validate exits 2 when configuration file does not exist."""
    missing_file = tmp_path / "nonexistent.yaml"
    result = run_diaglab_cli(["config", "validate", "--config", str(missing_file)])
    assert result.returncode == 2
    assert "INPUT_MISSING" in result.stderr


# ==============================================================================
# TC-I-01: diaglab manifest create tests
# ==============================================================================


def test_tc_i_01_manifest_create_success(valid_config_file: Path, tmp_path: Path) -> None:
    """TC-I-01: manifest create exits 0 and writes manifest.json in a clean directory."""
    out_dir = tmp_path / "run_out"
    result = run_diaglab_cli(
        ["manifest", "create", "--config", str(valid_config_file), "--output", str(out_dir)]
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "planned"
    manifest_path = Path(payload["manifest"])
    assert manifest_path.is_file()
    assert manifest_path.name == "manifest.json"

    # Verify manifest content
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest_data = json.load(f)
    assert manifest_data["state"] == "planned"
    assert manifest_data["schema_version"] == "1.0"


def test_tc_i_01_manifest_create_refuses_populated_destination_exit_1(
    valid_config_file: Path, tmp_path: Path
) -> None:
    """TC-I-01: manifest create exits 1 (PREFLIGHT_REFUSED) if output directory contains files."""
    populated_dir = tmp_path / "already_has_files"
    populated_dir.mkdir()
    (populated_dir / "leftover.log").write_text("data", encoding="utf-8")

    result = run_diaglab_cli(
        ["manifest", "create", "--config", str(valid_config_file), "--output", str(populated_dir)]
    )
    assert result.returncode == 1
    assert "PREFLIGHT_REFUSED" in result.stderr
    assert "absent or empty" in result.stderr.lower()


def test_tc_i_01_manifest_create_refuses_symlinked_destination_exit_1(
    valid_config_file: Path, tmp_path: Path
) -> None:
    """TC-I-01: manifest create exits 1 (PREFLIGHT_REFUSED) if output directory is a symlink."""
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    link_dir = tmp_path / "symlink_dir"
    os.symlink(real_dir, link_dir)

    result = run_diaglab_cli(
        ["manifest", "create", "--config", str(valid_config_file), "--output", str(link_dir)]
    )
    assert result.returncode == 1
    assert "PREFLIGHT_REFUSED" in result.stderr
    assert "symlink" in result.stderr.lower()


# ==============================================================================
# TC-I-01: Usage and Entrypoint Tests
# ==============================================================================


@pytest.mark.parametrize(
    "invalid_cli_args",
    [
        [],  # No command
        ["config"],  # Incomplete command
        ["manifest"],  # Incomplete command
        ["config", "validate"],  # Missing --config
        ["manifest", "create", "--config", "foo.yaml"],  # Missing --output
        ["unknown_subcommand"],  # Invalid subcommand
    ],
)
def test_tc_i_01_cli_usage_errors_exit_2(invalid_cli_args: list[str]) -> None:
    """TC-I-01: Command-line syntax and usage errors exit with code 2."""
    result = run_diaglab_cli(invalid_cli_args)
    assert result.returncode == 2


def test_tc_i_01_cli_version_flag() -> None:
    """TC-I-01: diaglab --version reports current version and exits 0."""
    result = run_diaglab_cli(["--version"])
    assert result.returncode == 0
    assert "0.1.0" in result.stdout or "0.1.0" in result.stderr


# ==============================================================================
# IMPL-B-2 & Exit Code 3 CLI Regressions
# ==============================================================================


@pytest.mark.parametrize(
    "role",
    ["warmup", "pilot", "evaluation", "overhead"],
)
def test_tc_i_01_manifest_create_explicit_run_role(
    valid_config_file: Path, tmp_path: Path, role: str
) -> None:
    """TC-I-01 / IMPL-B-2: CLI supports --run-role selection across all valid roles."""
    out_dir = tmp_path / f"manifest_{role}"
    result = run_diaglab_cli(
        [
            "manifest",
            "create",
            "--config",
            str(valid_config_file),
            "--output",
            str(out_dir),
            "--run-role",
            role,
        ]
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "planned"
    manifest_path = Path(payload["manifest"])
    with manifest_path.open("r", encoding="utf-8") as f:
        manifest_data = json.load(f)
    assert manifest_data["run_role"] == role


def test_tc_i_01_manifest_create_rejects_invalid_run_role(
    valid_config_file: Path, tmp_path: Path
) -> None:
    """TC-I-01 / IMPL-B-2: CLI rejects invalid --run-role choice with exit code 2."""
    out_dir = tmp_path / "invalid_role_dir"
    result = run_diaglab_cli(
        [
            "manifest",
            "create",
            "--config",
            str(valid_config_file),
            "--output",
            str(out_dir),
            "--run-role",
            "invalid_choice",
        ]
    )
    assert result.returncode == 2
    assert "invalid choice" in result.stderr.lower()


def test_tc_i_01_cli_unexpected_error_exit_3() -> None:
    """TC-I-01: Unexpected internal exceptions exit with code 3."""
    env = os.environ.copy()
    env["PYTHONPATH"] = "." + os.pathsep + env.get("PYTHONPATH", "")
    code = (
        "import sys, unittest.mock as mock, diaglab.cli as cli; "
        "mock.patch('diaglab.cli.load_config', "
        "side_effect=RuntimeError('disk corruption')).start(); "
        "sys.exit(cli.main(['config', 'validate', '--config', 'dummy.yaml']))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 3
    assert "EXECUTION_FAILED: unexpected internal error" in result.stderr
