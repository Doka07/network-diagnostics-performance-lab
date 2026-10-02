"""Optional desktop entrypoint; importing the core never imports Qt."""

import argparse
import sys
from pathlib import Path


def __getattr__(name):
    if name == "MainWindow":
        from diaglab.gui.window import MainWindow

        return MainWindow
    raise AttributeError(name)


def main(argv=None):
    if sys.platform.startswith("win"):
        print("diaglab-gui is Linux-only in this release.", file=sys.stderr)
        return 2
    parser = argparse.ArgumentParser(description="Inspect saved diagnostic runs offline")
    parser.add_argument("--run", type=Path)
    args = parser.parse_args(argv)
    try:
        from PySide6.QtWidgets import QApplication

        from diaglab.gui.window import MainWindow
    except ImportError:
        print("Install the gui extra: python -m pip install -e '.[gui]'", file=sys.stderr)
        return 2
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("DiagLab")
    window = MainWindow()
    window.show()
    if args.run:
        window.open_run(args.run)
    return app.exec()
