"""Create a planned manifest without traffic, privileges, or invented results."""

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from diaglab import __version__
from diaglab.artifacts.checksums import open_directory
from diaglab.config import ExperimentConfig
from diaglab.exceptions import ArtifactIntegrityError, SafetyPreflightError
from diaglab.validation import validate_record


def new_run_id() -> str:
    return "r-" + uuid4().hex


def source_hash() -> str:
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.suffix in {".py", ".json"}:
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def planned_manifest(config: ExperimentConfig, *, run_role: str = "pilot") -> dict:
    data = config.to_dict()
    manifest = {
        "schema_version": "1.0",
        "run_id": new_run_id(),
        "campaign_id": data["campaign_id"],
        "evidence_kind": data["evidence_kind"],
        "run_role": run_role,
        "state": "planned",
        "created_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "eligibility": {"status": "pending", "reasons": []},
        "code_sha256": source_hash(),
        "build_version": __version__,
        "config_sha256": config.sha256,
        "campaign_settings_sha256": None,
        "scenario_profile_sha256": None,
        "environment_reference": None,
        "expected_collectors": data["telemetry"]["collectors"],
        "collector_coverage": [],
        "events": [],
        "artifacts": [],
        "cleanup": {"status": "not_applicable", "reasons": []},
        "ground_truth_reference": None,
        "agent_sessions": [],
        "clock_records": [],
        "public_field_policy": "private_until_reviewed_export",
    }
    validate_record("manifest", manifest)
    return manifest


def create_run_manifest(
    config: ExperimentConfig, output: str | Path, *, run_role: str = "pilot"
) -> Path:
    record = planned_manifest(config, run_role=run_role)
    output = Path(output)
    # Refuse symlinked ancestors even when they currently resolve inside a safe directory.
    for part in (output, *output.parents):
        if part.is_symlink():
            raise SafetyPreflightError("manifest destination contains a symlink")
    try:
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise SafetyPreflightError("manifest destination must be absent or empty")
        directory = open_directory(output, create=True)
        lock_owned = False
        try:
            lock = os.open(
                ".creation.lock",
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            lock_owned = True
            os.close(lock)
            if os.listdir(directory) != [".creation.lock"]:
                raise SafetyPreflightError("manifest destination must be absent or empty")
            fd = os.open(
                "manifest.json",
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, indent=2, ensure_ascii=False, allow_nan=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(directory)
            return output / "manifest.json"
        finally:
            if lock_owned:
                os.unlink(".creation.lock", dir_fd=directory)
            os.close(directory)
    except FileExistsError as exc:
        raise SafetyPreflightError("manifest destination was populated concurrently") from exc
    except OSError as exc:
        raise ArtifactIntegrityError(f"cannot create manifest: {exc}") from exc
