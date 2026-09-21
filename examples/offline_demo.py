"""Purpose: Offline demo: screen 30 synthetic records with fixture probabilities, then print PRISMA counts,
the ranked reading order and agreement against synthetic human labels. No API key, no network call."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from jev_screen.cli import main

HERE = Path(__file__).resolve().parent


def run() -> int:
    # The CLI reports progress on stderr; line buffering keeps both streams readable when the demo is piped.
    sys.stdout.reconfigure(line_buffering=True)
    with tempfile.TemporaryDirectory(prefix="jev-screen-demo-") as tmp:
        out = Path(tmp) / "decisions.csv"
        cache = Path(tmp) / "cache.json"
        base = [
            "screen", str(HERE / "records.ris"),
            "--criteria", str(HERE / "criteria.json"),
            "--out", str(out),
            "--export-dir", str(Path(tmp) / "exports"),
            "--fake", str(HERE / "fixtures.json"),
            "--cache", str(cache),
        ]
        print("== estimate (no call) ==")
        if main(["estimate", str(HERE / "records.ris"), "--criteria", str(HERE / "criteria.json")]) != 0:
            return 1
        print("\n== screen with fake fixtures (synthetic probabilities, not measured Jev output) ==")
        if main(base) != 0:
            return 1
        print("\n== second run: every judged record comes from the cache ==")
        if main(base + ["--no-resume"]) != 0:
            return 1
        print("\n== prisma ==")
        if main(["prisma", str(out)]) != 0:
            return 1
        print("\n== rank (top 8) ==")
        if main(["rank", str(out), "--top", "8"]) != 0:
            return 1
        print("\n== agreement vs synthetic human labels ==")
        if main(["agreement", str(out), str(HERE / "human.csv")]) != 0:
            return 1
        exports = sorted(p.name for p in (Path(tmp) / "exports").iterdir())
        print("\nExports:", ", ".join(exports))
    print("\nDemo finished: offline, synthetic data only.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
