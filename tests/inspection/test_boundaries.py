"""TG-09 import/packaging boundary and TG-10 no-live-path checks (GC-10, GC-11, R-18).

Headless: these run in the ordinary CI job without the gui extra. They inspect source
statically and run interpreters in subprocesses; they never import Qt in this process.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
VIEWER_PACKAGES = ("inspection", "presentation", "gui")

FORBIDDEN_MODULE_PREFIXES = (
    "subprocess",
    "socket",
    "multiprocessing",
    "asyncio.subprocess",
    "http",
    "urllib",
    "ftplib",
    "smtplib",
    "telnetlib",
    "ssl",
    "webbrowser",
    "paramiko",
    "PySide6.QtNetwork",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "diaglab.traffic.runner",
)
FORBIDDEN_NAMES = {
    "run_experiment",
    "Iperf3TrafficAdapter",
    "QProcess",
    "QDesktopServices",
    "QSettings",
    "QNetworkAccessManager",
    "QTcpSocket",
    "QUdpSocket",
    "QWebEngineView",
    "system",  # os.system
    "popen",  # os.popen
    "execv",
    "execvp",
    "spawnv",
    "fork",
}
QT_ROOTS = ("PySide6", "shiboken6", "PyQt5", "PyQt6", "PySide2")


def viewer_sources() -> list[Path]:
    files: list[Path] = []
    for name in VIEWER_PACKAGES:
        package = REPO / "diaglab" / name
        module = REPO / "diaglab" / f"{name}.py"
        if package.is_dir():
            files.extend(sorted(package.rglob("*.py")))
        elif module.is_file():
            files.append(module)
        else:
            pytest.fail(f"diaglab.{name} is required by docs/GUI_CONTRACTS.md and is missing")
    return files


def imported_modules(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, (ast.Name, ast.Attribute))
            and getattr(node.func, "attr", getattr(node.func, "id", ""))
            in (
                "import_module",
                "__import__",
            )
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            found.add(str(node.args[0].value))
    return found


def used_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.split(".")[-1])
    return names


# ------------------------------------------------------------------- TG-10 static


def test_tg10_viewer_code_has_no_process_network_or_runner_path() -> None:
    problems = []
    for path in viewer_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in imported_modules(tree):
            if any(module == p or module.startswith(p + ".") for p in FORBIDDEN_MODULE_PREFIXES):
                problems.append(f"{path.relative_to(REPO)} imports {module}")
        for name in FORBIDDEN_NAMES & used_names(tree):
            problems.append(f"{path.relative_to(REPO)} references {name}")
    assert not problems, "\n".join(problems)


def test_tg10_core_and_presentation_never_import_qt() -> None:
    problems = []
    for path in viewer_sources():
        if "/gui/" in path.as_posix() or path.name == "gui.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module in imported_modules(tree):
            if module.split(".")[0] in QT_ROOTS:
                problems.append(f"{path.relative_to(REPO)} imports {module}")
    assert not problems, "\n".join(problems)


# ---------------------------------------------------------------- TG-09 runtime


def _python(code: str, *, block_qt: bool = False, extra_env: dict | None = None):
    prelude = ""
    if block_qt:
        prelude = f"import sys\nfor _name in {QT_ROOTS!r}:\n    sys.modules[_name] = None\n"
    import os

    env = dict(os.environ)
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, "-c", prelude + code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=REPO,
        env=env,
    )


def test_tg09_core_imports_load_no_qt_module() -> None:
    result = _python(
        "import sys\n"
        "import diaglab, diaglab.cli, diaglab.run, diaglab.traffic.parser\n"
        "import diaglab.inspection, diaglab.presentation\n"
        f"print(sorted(m for m in sys.modules if m.split('.')[0] in {QT_ROOTS!r}))\n"
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_tg09_cli_verify_works_with_qt_unavailable(matrix) -> None:
    result = _python(
        "import sys\n"
        "from diaglab.cli import main\n"
        f"sys.exit(main(['verify', '--run', {str(matrix['captured_success'])!r}]))\n",
        block_qt=True,
    )
    assert result.returncode == 0, result.stderr


def test_tg09_gui_entry_without_qt_exits_2_with_install_hint() -> None:
    result = _python(
        "import runpy\nrunpy.run_module('diaglab.gui', run_name='__main__')\n", block_qt=True
    )
    assert result.returncode == 2, (result.returncode, result.stderr)
    assert "gui" in (result.stderr + result.stdout)
    assert "Traceback" not in result.stderr


def test_tg09_gui_entry_on_windows_exits_2_with_linux_only_message() -> None:
    result = _python(
        "import sys\nsys.platform = 'win32'\n"
        "import runpy\nrunpy.run_module('diaglab.gui', run_name='__main__')\n",
        block_qt=True,
    )
    assert result.returncode == 2, (result.returncode, result.stderr)
    assert "linux" in (result.stderr + result.stdout).casefold()
    assert "Traceback" not in result.stderr


def test_tg09_packaging_keeps_qt_optional() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert not [dep for dep in project["dependencies"] if dep.lower().startswith("pyside6")]
    gui = project["optional-dependencies"]["gui"]
    pyside = [dep.replace(" ", "") for dep in gui if dep.lower().startswith("pyside6")]
    assert pyside == ["PySide6>=6.10,<7"]
    assert project["scripts"]["diaglab-gui"].startswith("diaglab.gui")
