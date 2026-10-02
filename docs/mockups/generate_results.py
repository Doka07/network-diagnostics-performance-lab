"""Generate a synthetic results example, never measured performance evidence.

Run from the repository: .venv/bin/python docs/mockups/generate_results.py
Uses dev fixtures and fake processes with network hooks replaced; no LAN traffic.
"""

import json
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from diaglab.results import export_results  # noqa: E402
from tests.inspection.runs import RunBuilder  # noqa: E402


def main():
    with tempfile.TemporaryDirectory(prefix="diaglab-results-example-") as temporary:
        root = Path(temporary)
        config = yaml.safe_load((ROOT / "configs/baseline.yaml").read_text())
        # The runner executes only pilot configs. These dev fixtures replace all
        # traffic hooks; preserve their recorded kind and label the preview below.
        config["evidence_kind"] = "pilot"
        config["campaign_id"] = "c-synthetic-report-example"
        builder = RunBuilder(root / "sources", config)
        completed = builder.synthetic("illustration", streams=4, retained=5, omitted=2)
        planned = builder.offline_plan()
        failed = builder._execute(
            "failed",
            json.dumps({"error": "synthetic error"}),
            duration_s=3,
            streams=1,
            returncode=1,
        )
        target = root / "report"
        export_results([completed, planned, failed, root / "missing-source"], target)
        report = json.loads((target / "summary.json").read_text())
        rows = report["runs"]
        assert [row["state"] for row in rows] == ["completed", "planned", "failed", None]
        assert all(row["integrity"] == "verified" for row in rows[:3])
        assert all(row["evidence_kind"] == "pilot" for row in rows[:3])
        assert rows[0]["result_verified"] is True
        assert rows[0]["metrics"]["receiver_goodput_bps"] > 0
        assert rows[0]["goodput_evidence"]
        assert rows[3]["issue_codes"] == ["INPUT_MISSING"]
        assert all(value is None for row in rows[1:] for value in row["metrics"].values())
        # Preview-only annotation, outside the core renderer and checksum bundle.
        # Do not relabel evidence or modify the generated summary/raw source files.
        banner = (
            "<aside class='notice'><strong>SYNTHETIC PREVIEW — NO LIVE MEASUREMENTS</strong>"
            "<p>All values below come from fake-process development fixtures. The pilot "
            "labels reflect the fixture manifests, not hardware experiments. "
            "Do not use these numbers as performance evidence.</p></aside>"
        )
        html = (target / "report.html").read_text()
        assert html.count("<body>") == 1
        html = html.replace("<body>", "<body>" + banner, 1)
        Path(__file__).with_name("results.html").write_text(html)
        print("Saved docs/mockups/results.html: synthetic illustration only")


if __name__ == "__main__":
    main()
