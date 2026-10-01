"""Independent unit tests for TC-U-04 and TC-U-04B.

TC-U-04: Manifest Generator & Structure
- Validates planned manifest structure against schema.
- Asserts run ID format, state, role, code SHA-256, config SHA-256.
- Tests regular file hashing via artifact_digest.

TC-U-04B: Path Traversal & Symlink Protection
- Rejects path traversal (../), absolute paths, Windows drive/backslash paths.
- Rejects symlinks within artifact root or relative paths.
- Asserts create_run_manifest refuses populated destinations or symlinked ancestors.
"""

import json
import os
from pathlib import Path
from typing import Any

import pytest

from diaglab.artifacts.checksums import artifact_digest, safe_artifact_path
from diaglab.artifacts.manifest import create_run_manifest, planned_manifest
from diaglab.config import ExperimentConfig
from diaglab.exceptions import ArtifactIntegrityError, SafetyPreflightError

# ==============================================================================
# TC-U-04: Manifest Generator Tests
# ==============================================================================


def test_tc_u_04_planned_manifest_structure(valid_config_dict: dict[str, Any]) -> None:
    """TC-U-04: planned_manifest generates a schema-compliant planned manifest."""
    config = ExperimentConfig.from_dict(valid_config_dict)
    manifest = planned_manifest(config)

    assert manifest["schema_version"] == "1.0"
    assert manifest["campaign_id"] == "c-test-001"
    assert manifest["evidence_kind"] == "pilot"
    assert manifest["run_role"] == "pilot"
    assert manifest["state"] == "planned"
    assert manifest["run_id"].startswith("r-")
    assert len(manifest["run_id"]) == 34  # 'r-' + 32 hex chars
    assert manifest["created_at_utc"].endswith("Z")
    assert manifest["eligibility"] == {"status": "pending", "reasons": []}
    assert manifest["cleanup"] == {"status": "not_applicable", "reasons": []}
    assert manifest["config_sha256"] == config.sha256
    assert len(manifest["code_sha256"]) == 64
    assert len(manifest["expected_collectors"]) == 4


def test_tc_u_04_standalone_manifest_defaults_to_pilot_and_allows_explicit_role(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-04 / IMPL-B-2: Standalone planning defaults to pilot; explicit role is supported."""
    valid_config_dict["evidence_kind"] = "measured"
    config = ExperimentConfig.from_dict(valid_config_dict)

    # Standalone planning defaults to pilot regardless of evidence_kind
    manifest_default = planned_manifest(config)
    assert manifest_default["evidence_kind"] == "measured"
    assert manifest_default["run_role"] == "pilot"

    # Explicit role selection via planned_manifest
    manifest_explicit = planned_manifest(config, run_role="evaluation")
    assert manifest_explicit["evidence_kind"] == "measured"
    assert manifest_explicit["run_role"] == "evaluation"

    # Explicit role selection via create_run_manifest
    out_dir = tmp_path / "run_eval"
    manifest_file = create_run_manifest(config, out_dir, run_role="evaluation")
    assert manifest_file.is_file()
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert data["run_role"] == "evaluation"
    assert data["evidence_kind"] == "measured"


@pytest.mark.parametrize(
    "evidence_kind",
    ["pilot", "measured", "synthetic"],
)
@pytest.mark.parametrize(
    "run_role",
    ["warmup", "pilot", "evaluation", "overhead"],
)
def test_tc_u_04_all_run_roles_across_evidence_kinds(
    valid_config_dict: dict[str, Any], evidence_kind: str, run_role: str
) -> None:
    """TC-U-04 / IMPL-B-2: Verify independence of all (evidence_kind, run_role) pairs."""
    valid_config_dict["evidence_kind"] = evidence_kind
    config = ExperimentConfig.from_dict(valid_config_dict)
    manifest = planned_manifest(config, run_role=run_role)

    assert manifest["evidence_kind"] == evidence_kind
    assert manifest["run_role"] == run_role


@pytest.mark.parametrize(
    "invalid_role",
    ["benchmark", "invalid", "", "PILOT", "production"],
)
def test_tc_u_04_reject_invalid_run_role(
    tmp_path: Path, valid_config_dict: dict[str, Any], invalid_role: str
) -> None:
    """TC-U-04 / IMPL-B-2: Reject invalid run_role values not in schema enum."""
    config = ExperimentConfig.from_dict(valid_config_dict)
    with pytest.raises(ArtifactIntegrityError) as exc_info:
        planned_manifest(config, run_role=invalid_role)
    assert "run_role" in str(exc_info.value)

    out_dir = tmp_path / f"invalid_role_{invalid_role}"
    with pytest.raises(ArtifactIntegrityError) as exc_info:
        create_run_manifest(config, out_dir, run_role=invalid_role)
    assert "run_role" in str(exc_info.value)


def test_tc_u_04_artifact_digest_valid_file(tmp_path: Path) -> None:
    """TC-U-04: artifact_digest calculates correct size and SHA-256 for a regular file."""
    root = tmp_path / "artifacts"
    root.mkdir()
    sample = root / "sample.txt"
    content = b"network diagnostics lab test content\n"
    sample.write_bytes(content)

    digest = artifact_digest(root, "sample.txt")
    assert digest["path"] == "sample.txt"
    assert digest["size_bytes"] == len(content)
    assert len(digest["sha256"]) == 64


def test_tc_u_04_artifact_digest_rejects_directory(tmp_path: Path) -> None:
    """TC-U-04: artifact_digest raises ArtifactIntegrityError if target is a directory."""
    root = tmp_path / "artifacts"
    root.mkdir()
    sub = root / "subdir"
    sub.mkdir()

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        artifact_digest(root, "subdir")
    assert "regular" in str(exc_info.value).lower()


# ==============================================================================
# TC-U-04B: Path Traversal & Symlink Guard Tests
# ==============================================================================


@pytest.mark.parametrize(
    "traversal_path",
    [
        "../escape.txt",
        "../../etc/passwd",
        "sub/../../escape.txt",
        "sub/../..",
    ],
)
def test_tc_u_04b_reject_path_traversal(tmp_path: Path, traversal_path: str) -> None:
    """TC-U-04B: safe_artifact_path must strictly reject paths containing '..'."""
    root = tmp_path / "artifacts"
    root.mkdir()

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        safe_artifact_path(root, traversal_path)
    assert "normalized" in str(exc_info.value).lower() or "relative" in str(exc_info.value).lower()


@pytest.mark.parametrize(
    "illegal_path",
    [
        "/etc/passwd",
        "/tmp/abs_file.txt",
        "C:\\Windows\\System32",
        "dir\\file.txt",
        "./relative.txt",
        "dir//double_slash.txt",
        ".",
        "",
    ],
)
def test_tc_u_04b_reject_non_normalized_or_absolute_paths(
    tmp_path: Path, illegal_path: str
) -> None:
    """TC-U-04B: Rejects absolute, Windows drive, backslash, and non-normalized relative paths."""
    root = tmp_path / "artifacts"
    root.mkdir()

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        safe_artifact_path(root, illegal_path)
    assert "normalized" in str(exc_info.value).lower() or "relative" in str(exc_info.value).lower()


def test_tc_u_04b_reject_symlink_in_artifact_path(tmp_path: Path) -> None:
    """TC-U-04B: Rejects paths containing symlinked components."""
    root = tmp_path / "artifacts"
    root.mkdir()
    target = tmp_path / "real_dir"
    target.mkdir()
    (target / "data.txt").write_text("hello", encoding="utf-8")

    link = root / "symlink_dir"
    os.symlink(target, link)

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        safe_artifact_path(root, "symlink_dir/data.txt")
    assert "symlinks" in str(exc_info.value).lower()


def test_tc_u_04b_reject_symlinked_root_directory(tmp_path: Path) -> None:
    """TC-U-04B: Rejects root directory if root itself is a symlink."""
    real_root = tmp_path / "real_root"
    real_root.mkdir()
    link_root = tmp_path / "symlink_root"
    os.symlink(real_root, link_root)

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        safe_artifact_path(link_root, "file.txt")
    assert "root" in str(exc_info.value).lower()


def test_tc_u_04b_manifest_create_success_in_new_directory(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-04B: create_run_manifest succeeds in an absent or clean directory."""
    config = ExperimentConfig.from_dict(valid_config_dict)
    output_dir = tmp_path / "new_run_dir"

    manifest_file = create_run_manifest(config, output_dir)
    assert manifest_file.is_file()
    assert manifest_file.name == "manifest.json"
    assert manifest_file.parent == output_dir

    # Check file permissions are 0600 (owner read/write only)
    stat_mode = manifest_file.stat().st_mode & 0o777
    assert stat_mode == 0o600


def test_tc_u_04b_manifest_create_refuses_populated_directory(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-04B: create_run_manifest refuses to write to a directory that already contains files."""
    config = ExperimentConfig.from_dict(valid_config_dict)
    output_dir = tmp_path / "populated_dir"
    output_dir.mkdir()
    (output_dir / "pre_existing_file.log").write_text("content", encoding="utf-8")

    with pytest.raises(SafetyPreflightError) as exc_info:
        create_run_manifest(config, output_dir)
    assert "absent or empty" in str(exc_info.value).lower()


def test_tc_u_04b_manifest_create_refuses_symlinked_destination(
    tmp_path: Path, valid_config_dict: dict[str, Any]
) -> None:
    """TC-U-04B: create_run_manifest refuses output destination containing a symlinked component."""
    config = ExperimentConfig.from_dict(valid_config_dict)
    real_dir = tmp_path / "real_dest"
    real_dir.mkdir()
    link_dir = tmp_path / "symlinked_dest"
    os.symlink(real_dir, link_dir)

    with pytest.raises(SafetyPreflightError) as exc_info:
        create_run_manifest(config, link_dir)
    assert "symlink" in str(exc_info.value).lower()
