"""Offline planning/verification and explicitly selected baseline execution."""

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from diaglab import __version__
from diaglab.artifacts.manifest import create_run_manifest
from diaglab.artifacts.store import ArtifactStore
from diaglab.config import load_config
from diaglab.exceptions import DiaglabError
from diaglab.run import run_experiment, verify_run
from diaglab.validation import parse_json

LOGGER = logging.getLogger("diaglab")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        prog="diaglab", description="TCP lab planning and baseline tools"
    )
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    config = commands.add_parser("config", help="validate experiment configuration")
    config_commands = config.add_subparsers(dest="action", required=True)
    validate = config_commands.add_parser("validate", help="offline validation; no host commands")
    validate.add_argument("--config", required=True)
    manifest = commands.add_parser("manifest", help="create a planned run manifest")
    manifest_commands = manifest.add_subparsers(dest="action", required=True)
    create = manifest_commands.add_parser("create", help="create in an absent or empty directory")
    create.add_argument("--config", required=True)
    create.add_argument("--output", required=True)
    # Phase 2 orchestration must supply each run's actual role explicitly.
    create.add_argument(
        "--run-role", choices=("warmup", "pilot", "evaluation", "overhead"), default="pilot"
    )
    run = commands.add_parser("run", help="plan offline; --execute selects live baseline traffic")
    run.add_argument("--config", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--execute", action="store_true")
    run.add_argument("--run-role", choices=("warmup", "pilot"), default="pilot")
    verify = commands.add_parser("verify", help="offline artifact/checksum verification")
    verify.add_argument("--run", required=True)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "verify":
            verification = verify_run(Path(args.run))
            result = {
                "verified": verification.verified,
                "state": verification.state,
                "transfer_completed": verification.transfer_completed,
                "result_verified": verification.result_verified,
                "reasons": list(verification.reasons),
            }
        elif args.command == "run":
            config = load_config(args.config)
            path = run_experiment(
                config, Path(args.output), execute=args.execute, run_role=args.run_role
            )
            verification = verify_run(path.parent)
            with ArtifactStore(path.parent) as store:
                run_id = parse_json(store.read("manifest.json").decode("utf-8"))["run_id"]
            result = {
                "run_id": run_id,
                "state": verification.state,
                "manifest": str(path),
                "result_verified": verification.result_verified,
            }
        elif args.command == "config":
            config = load_config(args.config)
            result = {
                "status": "valid",
                "schema_version": "1.0",
                "config_sha256": config.sha256,
                "live_preflight_performed": False,
            }
        else:
            config = load_config(args.config)
            path = create_run_manifest(config, args.output, run_role=args.run_role)
            result = {"status": "planned", "manifest": str(path)}
        print(json.dumps(result, allow_nan=False))
        return 0
    except DiaglabError as exc:
        print(f"{exc.code}: {exc}", file=sys.stderr)
        LOGGER.debug("command failed", exc_info=True)
        return exc.exit_code
    except KeyboardInterrupt:
        print("INTERRUPTED: operation interrupted", file=sys.stderr)
        return 130
    except Exception:
        LOGGER.debug("unexpected command failure", exc_info=True)
        print("EXECUTION_FAILED: unexpected internal error", file=sys.stderr)
        return 3
