"""Purpose: `jev-screen` command line: estimate, screen, prisma, agreement, rank. Errors go to stderr with exit code 1."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from .cache import ResultCache
from .client import DEFAULT_MODEL, FakeJev, JevClient, JevError, RateLimiter, estimate_cost_usd, estimate_tokens
from .criteria import CriteriaError, build_state, load_criteria
from .decision import EXCLUDE, INCLUDE, MAYBE, Decision
from .records import Record, check_unique_ids, load_records, write_csv, write_jsonl, write_ris
from .reports import agreement_report, format_agreement, format_prisma, prisma_counts, rank_rows, read_human_labels
from .screening import (
    ScreenResult,
    completed_ids,
    read_decisions,
    result_columns,
    result_row,
    screen_records,
)

DEFAULT_CACHE = ".jev-cache.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jev-screen",
        description="Title/abstract screening with Jev. Second screener or prioritizer; keep a human in the loop.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    est = sub.add_parser("estimate", help="count requests, tokens and estimated cost without calling Jev")
    est.add_argument("records", help="records file (.ris, .nbib or .csv)")
    est.add_argument("--criteria", required=True, help="criteria JSON")
    est.add_argument("--title-only", action="store_true", help="judge records without abstract from their title")
    est.add_argument("--json", action="store_true", help="print JSON instead of text")

    scr = sub.add_parser("screen", help="screen records and write decisions.csv (resumable)")
    scr.add_argument("records", help="records file (.ris, .nbib or .csv)")
    scr.add_argument("--criteria", required=True, help="criteria JSON")
    scr.add_argument("--out", required=True, help="decisions CSV (appended to on resume)")
    scr.add_argument("--export-dir", help="write included/excluded/maybe as RIS, CSV and JSONL here")
    scr.add_argument("--fake", metavar="FIXTURES", help="use fixture probabilities instead of the Jev API")
    scr.add_argument(
        "--cache", nargs="?", const=DEFAULT_CACHE, metavar="PATH", help=f"exact-input cache file (default {DEFAULT_CACHE})"
    )
    scr.add_argument("--title-only", action="store_true", help="judge records without abstract from their title")
    scr.add_argument("--concurrency", type=int, default=8, help="parallel requests (default 8)")
    scr.add_argument("--requests-per-minute", type=int, default=1000, help="in-process rate limit (default 1000)")
    scr.add_argument("--timeout", type=float, default=30.0, help="seconds per request (default 30)")
    scr.add_argument("--no-resume", action="store_true", help="overwrite --out instead of skipping done ids")

    pri = sub.add_parser("prisma", help="PRISMA screening counts from decisions.csv")
    pri.add_argument("decisions")
    pri.add_argument("--json", action="store_true")

    agr = sub.add_parser("agreement", help="kappa, recall, specificity, WSS@95 against human labels")
    agr.add_argument("decisions")
    agr.add_argument("human", help="CSV with columns id,decision (include/exclude)")
    agr.add_argument("--maybe-as", choices=[INCLUDE, EXCLUDE], default=INCLUDE, help="how to count tool 'maybe'")
    agr.add_argument("--recall-target", type=float, default=0.95, help="recall level for WSS (default 0.95)")
    agr.add_argument("--json", action="store_true")

    rnk = sub.add_parser("rank", help="reading order for human screeners, highest inclusion score first")
    rnk.add_argument("decisions")
    rnk.add_argument("--out", help="write the ranked CSV here instead of printing")
    rnk.add_argument("--top", type=int, default=0, help="print only the first N rows")
    return parser


def _load(records_path: str, criteria_path: str) -> tuple[list[Record], Any]:
    records = load_records(records_path)
    if not records:
        raise ValueError(f"no records found in {records_path}")
    check_unique_ids(records)
    return records, load_criteria(criteria_path)


def cmd_estimate(args: argparse.Namespace) -> int:
    records, criteria = _load(args.records, args.criteria)
    questions = criteria.questions()
    judged = 0
    tokens = 0
    without_abstract = 0
    for record in records:
        state = build_state(record)
        if "abstract" not in state:
            without_abstract += 1
            if not args.title_only or not state["title"]:
                continue
        judged += 1
        tokens += estimate_tokens({"model": DEFAULT_MODEL, "state": state, "questions": questions})
    summary = {
        "records": len(records),
        "without_abstract": without_abstract,
        "requests": judged,
        "criteria": len(criteria.all),
        "estimated_input_tokens": tokens,
        "estimated_cost_usd": round(estimate_cost_usd(tokens), 6),
        "note": "chars/4 estimate priced at USD 0.042 per million input tokens (published list); not a quote",
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Records: {summary['records']} (without abstract: {without_abstract})")
        print(f"Requests to Jev: {judged} ({len(criteria.all)} criteria each, one request per record)")
        print(f"Estimated input tokens: {tokens}")
        print(f"Estimated cost: USD {summary['estimated_cost_usd']:.4f} ({summary['note']})")
    return 0


def _export(export_dir: str, results: list[ScreenResult], criteria: Any) -> None:
    """Three buckets, three formats each: RIS for reference managers, CSV for spreadsheets, JSONL for scripts."""
    out = Path(export_dir)
    out.mkdir(parents=True, exist_ok=True)
    columns = result_columns(criteria)
    for bucket, name in ((INCLUDE, "included"), (EXCLUDE, "excluded"), (MAYBE, "maybe")):
        subset = [r for r in results if r.decision.label == bucket]
        notes = {r.record.id: f"jev-screen decision={r.decision.label}; reason={r.decision.reason}" for r in subset}
        write_ris([r.record for r in subset], out / f"{name}.ris", notes)
        rows = [{**result_row(r, criteria), "abstract": r.record.abstract} for r in subset]
        write_csv(rows, out / f"{name}.csv", columns + ["abstract"])
        write_jsonl(
            [{**r.record.to_dict(), "decision": r.decision.label, "reason": r.decision.reason, "probabilities": r.probabilities}
             for r in subset],
            out / f"{name}.jsonl",
        )


def cmd_screen(args: argparse.Namespace) -> int:
    records, criteria = _load(args.records, args.criteria)
    if args.fake:
        provider: Any = FakeJev.load(args.fake)
        print(f"Provider: fake fixtures {args.fake} (no network call)", file=sys.stderr)
    else:
        provider = JevClient(timeout_seconds=args.timeout, rate_limiter=RateLimiter(args.requests_per_minute))
        print("Provider: api.typesafe.ai (paid requests, title and abstract are sent)", file=sys.stderr)
    cache = ResultCache(args.cache) if args.cache else None
    out = Path(args.out)
    columns = result_columns(criteria)
    if args.no_resume and out.exists():
        out.unlink()
    done = completed_ids(out, criteria)
    if done:
        print(f"Resuming: {len(done)} of {len(records)} records already in {out}", file=sys.stderr)
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists() or out.stat().st_size == 0
    counts = {INCLUDE: 0, EXCLUDE: 0, MAYBE: 0}
    spent_tokens = 0
    cached_hits = 0
    with out.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if new_file:
            writer.writeheader()
            handle.flush()

        def on_result(result: ScreenResult) -> None:
            nonlocal spent_tokens, cached_hits
            writer.writerow(result_row(result, criteria))
            handle.flush()  # a crash later must not lose rows that were already paid for
            counts[result.decision.label] += 1
            if result.cached:
                cached_hits += 1
            else:
                spent_tokens += result.input_tokens

        try:
            screen_records(
                records,
                criteria,
                provider,
                cache=cache,
                title_only=args.title_only,
                concurrency=args.concurrency,
                skip_ids=done,
                on_result=on_result,
            )
        finally:
            if cache is not None:
                cache.save()
    print(
        f"Screened {sum(counts.values())} new records: include={counts[INCLUDE]} maybe={counts[MAYBE]} "
        f"exclude={counts[EXCLUDE]} (cache hits: {cached_hits}, input tokens spent: {spent_tokens}, "
        f"estimated cost USD {estimate_cost_usd(spent_tokens):.4f})",
        file=sys.stderr,
    )
    if args.export_dir:
        rows = read_decisions(out)
        by_id = {r.id: r for r in records}
        results = []
        for row in rows:
            record = by_id.get(row["id"])
            if record is None:
                continue  # rows from a previous run over a different records file are left out of the export
            probabilities = {cid: row[f"p_{cid}"] for cid in criteria.ids if row.get(f"p_{cid}") is not None}
            decision = Decision(row["decision"], row["reason"], row.get("inclusion_score"))
            results.append(ScreenResult(record, decision, probabilities, 0, True, row.get("model", ""), row.get("request_key", "")))
        _export(args.export_dir, results, criteria)
        print(f"Exports written to {args.export_dir}/ (included/excluded/maybe as .ris, .csv, .jsonl)", file=sys.stderr)
    print(str(out))
    return 0


def cmd_prisma(args: argparse.Namespace) -> int:
    counts = prisma_counts(read_decisions(args.decisions))
    print(json.dumps(counts, indent=2) if args.json else format_prisma(counts))
    return 0


def cmd_agreement(args: argparse.Namespace) -> int:
    rows = read_decisions(args.decisions)
    human, ignored = read_human_labels(args.human)
    report = agreement_report(rows, human, maybe_as=args.maybe_as, recall_target=args.recall_target)
    report["human_rows_with_other_label"] = ignored
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_agreement(report))
        if ignored:
            print(f"Human rows ignored (label not include/exclude): {ignored}")
    return 0


def cmd_rank(args: argparse.Namespace) -> int:
    ranked = rank_rows(read_decisions(args.decisions))
    if args.top > 0:
        ranked = ranked[: args.top]
    if args.out:
        columns = ["rank"] + [c for c in ranked[0].keys() if c != "rank"] if ranked else ["rank"]
        write_csv(ranked, args.out, columns)
        print(args.out)
        return 0
    for row in ranked:
        score = "  n/a" if row.get("inclusion_score") is None else f"{row['inclusion_score']:.3f}"
        title = (row.get("title") or "")[:70]
        print(f"{row['rank']:>4}  {score}  {row['decision']:<7}  {row['id']}  {title}")
    return 0


COMMANDS = {
    "estimate": cmd_estimate,
    "screen": cmd_screen,
    "prisma": cmd_prisma,
    "agreement": cmd_agreement,
    "rank": cmd_rank,
}


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (JevError, CriteriaError, ValueError, OSError, KeyError) as err:
        print(f"jev-screen: error: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
