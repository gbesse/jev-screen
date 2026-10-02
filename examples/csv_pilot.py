"""Show include, exclude and maybe decisions on three fictional CSV records.

Run ``PYTHONPATH=src python -m examples.csv_pilot`` from the repository root.
Probabilities are synthetic fixtures; no API call is made.
"""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

from jev_screen.cli import main

HERE = Path(__file__).resolve().parent


def run() -> int:
    with tempfile.TemporaryDirectory(prefix="jev-screen-csv-pilot-") as tmp:
        out = Path(tmp) / "decisions.csv"
        rc = main([
            "screen", str(HERE / "csv_pilot.csv"),
            "--criteria", str(HERE / "criteria.json"),
            "--out", str(out),
            "--fake", str(HERE / "fixtures.json"),
        ])
        if rc:
            return rc
        print("Fictional CSV pilot (synthetic probabilities; no API call)")
        with out.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                print(f"{row['id']}: {row['decision']} — {row['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(run())
