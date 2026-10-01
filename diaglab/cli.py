"""Phase 1 CLI. Both console and module entrypoints call main()."""

import argparse
import json
import logging
import sys
from collections.abc import Sequence

from diaglab import __version__
from diaglab.artifacts.manifest import create_run_manifest
from diaglab.config import load_config
from diaglab.exceptions import DiaglabError

LOGGER = logging.getLogger("diaglab")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="diaglab", description="Offline network lab planning tools")
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
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "config":
            result = {
                "status": "valid",
                "schema_version": "1.0",
                "config_sha256": config.sha256,
                "live_preflight_performed": False,
            }
        else:
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
