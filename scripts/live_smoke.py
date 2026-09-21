"""Purpose: Opt-in live smoke test: at most two real Jev requests with synthetic records, only when TYPESAFE_API_KEY is set.

Prints the answers, the decision, usage and the estimated cost; exits non-zero on any error. It is never run by
tests or CI; the maintainer runs it by hand after a release build.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jev_screen.client import JevClient, JevError  # noqa: E402
from jev_screen.criteria import build_state, load_criteria  # noqa: E402
from jev_screen.decision import decide  # noqa: E402
from jev_screen.records import Record  # noqa: E402

RECORDS = [
    Record(
        id="smoke-1",
        title="Smartphone coaching for glycaemic control in adults with type 2 diabetes: a randomized trial",
        abstract="We randomized 240 adults with type 2 diabetes to a smartphone coaching app or usual care. "
        "At six months HbA1c fell by 0.5 percentage points more in the app group.",
    ),
    Record(
        id="smoke-2",
        title="Hepatic insulin signalling in streptozotocin-treated mice fed a high-fat diet",
        abstract="Male mice were treated with streptozotocin and fed a high-fat diet. Hepatic insulin receptor "
        "phosphorylation was reduced and blood glucose rose.",
    ),
]


def main() -> int:
    if not os.environ.get("TYPESAFE_API_KEY"):
        print("live smoke skipped: TYPESAFE_API_KEY is not set (no request made)")
        return 0
    criteria = load_criteria(Path(__file__).resolve().parents[1] / "examples" / "criteria.json")
    client = JevClient(timeout_seconds=30, max_retries=1)
    total_tokens = 0
    try:
        for record in RECORDS:  # exactly two requests, one per record
            result = client.ask(build_state(record), criteria.questions())
            probabilities = {cid: result.answers[cid]["noul"] for cid in criteria.ids}
            decision = decide(criteria, probabilities)
            total_tokens += result.input_tokens
            print(json.dumps({
                "id": record.id,
                "model": result.model,
                "probabilities": probabilities,
                "decision": decision.label,
                "reason": decision.reason,
                "usage": result.usage,
                "estimated_cost_usd": round(result.estimated_cost_usd, 8),
            }, indent=2))
    except JevError as err:
        print(f"live smoke failed: {err}", file=sys.stderr)
        return 1
    print(f"requests: {client.calls}, input tokens: {total_tokens}, "
          f"estimated cost USD {total_tokens * 0.042 / 1e6:.8f} (published price list, not a quote)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
