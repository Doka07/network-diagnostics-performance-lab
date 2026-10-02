"""Fixtures for RT-01–08 (docs/RESULTS_CONTRACTS.md), written before diaglab.results existed.

Every input is a run directory produced by the accepted runner (mock iperf3, RFC 1918 test
addresses), so each case is evidence the real product can create. Tests receive copies.
"""

from __future__ import annotations

import copy
import importlib
import json
import shutil
from pathlib import Path
from types import ModuleType

import pytest
import yaml

# pytest's default "prepend" import mode puts tests/ on sys.path; this shares the one
# `inspection.runs` module object the GUI tests already use.
from inspection.runs import RunBuilder, clone, synthetic_document

from diaglab.config import ExperimentConfig
from diaglab.run import run_experiment

REPO = Path(__file__).resolve().parents[2]


def results() -> ModuleType:
    """The module under test. A missing module fails the test; it is never skipped."""
    return importlib.import_module("diaglab.results")


def zero_goodput_document() -> dict:
    """A self-consistent single-stream run whose receiver measured 0 bytes throughout.
    The accepted runner completes and verifies it with receiver goodput 0.0 bit/s."""
    document = synthetic_document(streams=1, retained=3)
    server = document["server_output_json"]
    for epoch in server["intervals"]:
        for row in [*epoch["streams"], epoch["sum"]]:
            row["bytes"], row["bits_per_second"] = 0, 0.0
    for side in (server["end"]["streams"], document["end"]["streams"]):
        for stream in side:
            stream["receiver"]["bytes"], stream["receiver"]["bits_per_second"] = 0, 0.0
    for total in (server["end"]["sum_received"], document["end"]["sum_received"]):
        total["bytes"], total["bits_per_second"] = 0, 0.0
    return document


def _plan(root: Path, base: dict, name: str, kind: str, role: str) -> Path:
    data = copy.deepcopy(base)
    data["evidence_kind"] = kind
    run_experiment(ExperimentConfig.from_dict(data), root / name, execute=False, run_role=role)
    return root / name


@pytest.fixture(scope="session")
def base_config() -> dict:
    with (REPO / "configs" / "baseline.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture(scope="session")
def pristine(tmp_path_factory: pytest.TempPathFactory, base_config: dict) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("results-matrix")
    builder = RunBuilder(root, base_config)
    zero = zero_goodput_document()
    runs = {
        "captured": builder.captured_success(),
        "four_omit": builder.synthetic("four_omit", streams=4, retained=5, omitted=2),
        "flow_flag": builder.synthetic("flow_flag", streams=4, retained=3, flow_without_seconds=2),
        "zero": builder._execute("zero", json.dumps(zero), duration_s=3, streams=1),
        "no_server": builder.synthetic("no_server", streams=1, retained=3, with_server=False),
        # Receiver data present, traffic result unverified (interval gap): never exported.
        "gap": builder.synthetic("gap", streams=1, retained=4, gap_after=2),
        "connection_timeout": builder.connection_timeout(),
        "interrupted": builder.interrupted(),
        "plan_synthetic_warmup": _plan(root, base_config, "plan_sw", "synthetic", "warmup"),
        "plan_measured_pilot": _plan(root, base_config, "plan_mp", "measured", "pilot"),
    }
    config_file = root / "baseline.yaml"
    config_file.write_text(yaml.safe_dump(base_config), encoding="utf-8")
    runs["phase1_manifest"] = builder.phase1_manifest(config_file)
    unfinalized = clone(runs["captured"], root / "unfinalized")
    (unfinalized / ".run.lock").touch()
    runs["unfinalized"] = unfinalized
    tampered = clone(runs["captured"], root / "tampered")
    with (tampered / "client.stderr").open("ab") as handle:
        handle.write(b"tampered after finalization")
    runs["tampered"] = tampered
    zero_manifest = json.loads((runs["zero"] / "manifest.json").read_text())
    assert zero_manifest["state"] == "completed", "zero-goodput fixture must complete"
    return runs


@pytest.fixture
def fresh(pristine: dict[str, Path], tmp_path: Path):
    """Independent copies; repeated names get numeric suffixes (distinct directories)."""
    counts: dict[str, int] = {}

    def make(name: str) -> Path:
        index = counts.get(name, 0)
        counts[name] = index + 1
        destination = tmp_path / "inputs" / (name if index == 0 else f"{name}-{index}")
        destination.parent.mkdir(exist_ok=True)
        return clone(pristine[name], destination)

    return make


@pytest.fixture
def out(tmp_path: Path) -> Path:
    """An absent output directory outside every input."""
    return tmp_path / "exports" / "bundle"


def cli(argv: list[str], capsys: pytest.CaptureFixture) -> tuple[int, str, str]:
    from diaglab.cli import main

    try:
        code = main(argv)
    except SystemExit as exc:  # argparse usage errors
        code = exc.code if isinstance(exc.code, int) else 2
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def results_argv(runs: list[Path], output: Path) -> list[str]:
    argv = ["results"]
    for run in runs:
        argv += ["--run", str(run)]
    return argv + ["--output", str(output)]


def remove(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
