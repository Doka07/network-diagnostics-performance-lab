"""Regenerate synthetic previews: QT_QPA_PLATFORM=offscreen python docs/mockups/generate.py.

Run from the repository with dev+gui extras installed. Uses only synthetic fixtures and
fake local processes; no network traffic. The screenshot-only banner replaces the path
label after loading; the shipped GUI itself is otherwise unchanged.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import yaml
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from diaglab.gui.window import MainWindow  # noqa: E402
from tests.inspection.runs import RunBuilder  # noqa: E402


def main():
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="diaglab-preview-") as temporary:
        root = Path(temporary)
        config = yaml.safe_load((ROOT / "configs/baseline.yaml").read_text())
        builder = RunBuilder(root, config)
        completed = builder.synthetic("completed", streams=4, retained=12, omitted=2)
        failed = builder._execute(
            "failed",
            json.dumps({"error": "synthetic connection failure"}),
            duration_s=3,
            streams=1,
            returncode=1,
        )
        interrupted = builder.interrupted()
        missing = builder.synthetic("missing-rtt", streams=4, retained=12, with_rtt=False)
        corrupt = Path(shutil.copytree(completed, root / "corrupt"))
        with (corrupt / "client.stderr").open("ab") as handle:
            handle.write(b"synthetic corruption")
        unfinalized = Path(shutil.copytree(completed, root / "unfinalized"))
        (unfinalized / ".run.lock").touch()
        cases = [
            ("completed-dark", completed, "dark"),
            ("completed-light", completed, "light"),
            ("failed-dark", failed, "dark"),
            ("interrupted-dark", interrupted, "dark"),
            ("integrity-failed-dark", corrupt, "dark"),
            ("unfinalized-dark", unfinalized, "dark"),
            ("unavailable-rtt-dark", missing, "dark"),
        ]
        for name, run, theme in cases:
            window = MainWindow()
            window.resize(1420, 900)
            window.show()
            window.theme.setCurrentText(theme.title())
            window.open_run(run)
            for _ in range(1000):
                QTest.qWait(10)
                if not window.is_loading():
                    break
            else:
                raise RuntimeError("Preview load timed out")
            if window.current_view is None:
                raise RuntimeError("Preview did not load")
            window.path_label.setText(
                "SYNTHETIC ILLUSTRATION · invented test values · not measured performance"
            )
            if window.chart.series and window.chart.series.points:
                window._point_details(window.chart.series.points[0])
            QTest.qWait(100)
            if not window.grab().save(str(Path(__file__).parent / f"{name}.png")):
                raise RuntimeError("Could not save preview")
            window.close()
            app.processEvents()
    print("Saved seven synthetic GUI previews.")


if __name__ == "__main__":
    main()
