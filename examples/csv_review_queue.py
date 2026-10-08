"""Export only unresolved synthetic screening records for a human reviewer."""

from __future__ import annotations

import csv
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from jev_screen.cli import main

HERE = Path(__file__).resolve().parent


def run() -> int:
    with tempfile.TemporaryDirectory(prefix="jev-screen-review-") as tmp:
        out = Path(tmp) / "decisions.csv"
        with redirect_stdout(io.StringIO()):
            rc = main([
                "screen", str(HERE / "csv_pilot.csv"),
                "--criteria", str(HERE / "criteria.json"),
                "--out", str(out),
                "--fake", str(HERE / "fixtures.json"),
            ])
        if rc:
            return rc
        writer = csv.DictWriter(sys.stdout, fieldnames=["id", "title", "decision", "reason", "inclusion_score"])
        writer.writeheader()
        with out.open(encoding="utf-8", newline="") as handle:
            unresolved = [row for row in csv.DictReader(handle) if row["decision"] == "maybe"]
            for row in sorted(unresolved, key=lambda item: (-float(item["inclusion_score"] or 0), item["id"])):
                writer.writerow({key: row[key] for key in writer.fieldnames})
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
