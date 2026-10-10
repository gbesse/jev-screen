"""Compare a synthetic human label with both explicit `maybe` policies.

Run with ``PYTHONPATH=src python3 -m examples.maybe_recall``.
No API call or TypeSafe key is needed.
"""

from __future__ import annotations

import json

from jev_screen.reports import agreement_report


def run() -> None:
    rows = [
        {"id": "synthetic-1", "decision": "maybe", "inclusion_score": 0.5},
        {"id": "synthetic-2", "decision": "exclude", "inclusion_score": 0.1},
    ]
    human = {"synthetic-1": True, "synthetic-2": False}
    include = agreement_report(rows, human, maybe_as="include")
    exclude = agreement_report(rows, human, maybe_as="exclude")
    assert include["confusion"]["tp"] == 1
    assert include["confusion"]["fn"] == 0
    assert exclude["confusion"]["tp"] == 0
    assert exclude["confusion"]["fn"] == 1
    print(json.dumps({"maybe_as_include": include["confusion"], "maybe_as_exclude": exclude["confusion"]}))


if __name__ == "__main__":
    run()
