"""Shared fixtures for the GUI steps 1-2 independent tests (docs/GUI_CONTRACTS.md + R-1..R-22).

The modules under test are imported lazily (`core()`, `view()`) so that, before the
implementation exists, each test fails individually with ModuleNotFoundError instead of
aborting collection of the whole repository suite. They are never skipped.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from .runs import RunBuilder, clone

REPO = Path(__file__).resolve().parents[2]


def core() -> ModuleType:
    return importlib.import_module("diaglab.inspection")


def view() -> ModuleType:
    return importlib.import_module("diaglab.presentation")


@pytest.fixture(scope="session")
def base_config() -> dict:
    with (REPO / "configs" / "baseline.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.fixture(scope="session")
def matrix(tmp_path_factory: pytest.TempPathFactory, base_config: dict) -> dict[str, Path]:
    """Pristine run directories, built once. Tests receive copies via `fresh`."""
    root = tmp_path_factory.mktemp("gui-matrix")
    builder = RunBuilder(root, base_config)
    config_file = root / "baseline.yaml"
    config_file.write_text(yaml.safe_dump(base_config), encoding="utf-8")
    return {
        "captured_success": builder.captured_success(),
        "connection_timeout": builder.connection_timeout(),
        "four_omit": builder.synthetic("four_omit", streams=4, retained=5, omitted=2),
        "four_derived": builder.synthetic(
            "four_derived", streams=4, retained=4, with_sum=False, with_rtt=False
        ),
        "flow_flag": builder.synthetic("flow_flag", streams=4, retained=3, flow_without_seconds=2),
        "no_server": builder.synthetic("no_server", streams=1, retained=3, with_server=False),
        "gap": builder.synthetic("gap", streams=1, retained=4, gap_after=2),
        "interrupted": builder.interrupted(),
        "offline_plan": builder.offline_plan(),
        "phase1_manifest": builder.phase1_manifest(config_file),
    }


@pytest.fixture(scope="session")
def large_run(tmp_path_factory: pytest.TempPathFactory, base_config: dict) -> Path:
    """Largest 4-stream run whose derived summary still fits 16 MiB: client.json ~10.5 MiB,
    traffic_summary.json ~14.6 MiB (ratio ~1.39; see P2-F1). Shared by the P2-F1
    boundary test and the Qt responsiveness tests."""
    builder = RunBuilder(tmp_path_factory.mktemp("large"), base_config)
    return builder.synthetic("large", streams=4, retained=6500)


@pytest.fixture
def fresh(matrix: dict[str, Path], tmp_path: Path):
    """Return an independent copy of a matrix run so tests may tamper with it.

    Every call gets its own destination, so one test may request the same run twice.
    The first copy keeps the plain name; later copies get a numeric suffix.
    """
    counts: dict[str, int] = {}

    def make(name: str) -> Path:
        index = counts.get(name, 0)
        counts[name] = index + 1
        destination = tmp_path / (name if index == 0 else f"{name}-{index}")
        return clone(matrix[name], destination)

    return make
