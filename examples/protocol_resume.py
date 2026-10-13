"""Synthetic protocol change: reject stale resume, then reapply policy to cached answers."""

from __future__ import annotations

import argparse
import copy
import io
import json
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from jev_screen.cli import main
from jev_screen.screening import read_decisions

MESSAGES = {
    "fr": "Exemple fictif : reprise obsolète bloquée ; nouvelle décision après changement de seuil, sans nouvel appel.",
    "en": "Fictional example: stale resume blocked; a new decision after a threshold change, without another call.",
    "es": "Ejemplo ficticio: reanudación obsoleta bloqueada; nueva decisión tras cambiar el umbral, sin otra llamada.",
}


def run(lang="en"):
    with tempfile.TemporaryDirectory(prefix="jev-screen-protocol-") as folder:
        root = Path(folder)
        records = root / "records.csv"
        records.write_text(
            "id,title,abstract\nsynthetic,FR : étude fictive / EN: fictional study / ES: estudio ficticio,FR : résumé fictif / EN: fictional abstract / ES: resumen ficticio\n"
        )
        criteria = root / "criteria.json"
        protocol = {
            "review": "FR : protocole fictif / EN: fictional protocol / ES: protocolo ficticio",
            "inclusion": [
                {
                    "id": "eligible",
                    "statement": "FR : étude fictive pertinente / EN: relevant fictional study / ES: estudio ficticio pertinente",
                }
            ],
            "thresholds": {"include_min": 0.7, "exclude_max": 0.3},
        }
        criteria.write_text(json.dumps(protocol, ensure_ascii=False))
        fixtures = root / "fixtures.json"
        fixtures.write_text(json.dumps({"default": {"eligible": 0.8}, "records": {}}))
        old = root / "old.csv"
        new = root / "new.csv"
        cache = root / "cache.json"
        args = [
            "screen",
            str(records),
            "--criteria",
            str(criteria),
            "--out",
            str(old),
            "--fake",
            str(fixtures),
            "--cache",
            str(cache),
        ]

        def invoke(extra=()):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                return main(args + list(extra))

        assert invoke(["--receipt", str(root / "old-receipt.json")]) == 0
        first = read_decisions(old)[0]
        assert first["decision"] == "include"
        before = old.read_bytes()
        changed = copy.deepcopy(protocol)
        changed["thresholds"]["include_min"] = 0.9
        criteria.write_text(json.dumps(changed, ensure_ascii=False))
        assert invoke() == 1
        assert old.read_bytes() == before
        args[args.index("--out") + 1] = str(new)
        assert invoke(["--receipt", str(root / "new-receipt.json")]) == 0
        after = read_decisions(new)[0]
        assert after["decision"] == "maybe" and after["cached"] == "1"
        assert after["protocol_sha256"] != first["protocol_sha256"]
        assert after["request_key"] == first["request_key"]
        summary = {
            "message": MESSAGES[lang],
            "synthetic": True,
            "paid_requests": 0,
            "stale_resume_rejected": True,
            "before": {
                "decision": first["decision"],
                "protocol_sha256": first["protocol_sha256"],
            },
            "after": {
                "decision": after["decision"],
                "protocol_sha256": after["protocol_sha256"],
                "cached": True,
            },
            "receipt": json.loads((root / "new-receipt.json").read_text()),
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="FR : reprise sourcée / EN: traceable resume / ES: reanudación trazable"
    )
    p.add_argument("--lang", choices=tuple(MESSAGES), default="en", help="FR / EN / ES")
    run(p.parse_args().lang)
