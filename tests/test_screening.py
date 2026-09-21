"""Purpose: Screening pipeline tests: fake path, cache hits, resume, no-abstract routing, exports, PRISMA, agreement, rank, CLI."""

import csv
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from jev_screen.cache import ResultCache
from jev_screen.cli import main
from jev_screen.client import FakeJev
from jev_screen.records import Record, to_ris
from jev_screen.reports import agreement_report, prisma_counts, rank_rows
from jev_screen.screening import completed_ids, read_decisions, result_columns, screen_one, screen_records
from tests.helpers import criteria

FIXTURES = {
    "records": {
        "Include me": {"population": 0.9, "intervention": 0.8, "animal": 0.1},
        "Exclude me": {"population": 0.1, "intervention": 0.8, "animal": 0.1},
        "Maybe me": {"population": 0.5, "intervention": 0.8, "animal": 0.1},
        "No abstract": {"population": 0.9, "intervention": 0.9, "animal": 0.1},
    }
}
RECORDS = [
    Record(id="r1", title="Include me", abstract="Adults with type 2 diabetes used an app."),
    Record(id="r2", title="Exclude me", abstract="Mice were fed a diet."),
    Record(id="r3", title="Maybe me", abstract="Adults with diabetes of unstated type."),
    Record(id="r4", title="No abstract"),
]


class ScreeningTest(unittest.TestCase):
    def test_buckets_and_provider_calls(self):
        fake = FakeJev(FIXTURES)
        results = screen_records(RECORDS, criteria(), fake, concurrency=2)
        labels = [(r.record.id, r.decision.label, r.decision.reason) for r in results]
        self.assertEqual(labels, [
            ("r1", "include", "all_criteria_met"),
            ("r2", "exclude", "inclusion:population"),
            ("r3", "maybe", "uncertain:population"),
            ("r4", "maybe", "no_abstract"),
        ])
        self.assertEqual(len(fake.calls), 3)  # the record without abstract is never sent
        self.assertEqual(set(fake.calls[0]["state"]), {"title", "abstract"})
        self.assertEqual(fake.calls[0]["questions"], ["population", "intervention", "animal"])

    def test_title_only_judges_records_without_abstract(self):
        fake = FakeJev(FIXTURES)
        result = screen_one(RECORDS[3], criteria(), fake, title_only=True)
        self.assertEqual(result.decision.label, "include")
        self.assertEqual(fake.calls[0]["state"], {"title": "No abstract"})

    def test_empty_record_is_unjudged(self):
        result = screen_one(Record(id="e", title="", abstract=""), criteria(), FakeJev(FIXTURES), title_only=True)
        self.assertEqual((result.decision.label, result.decision.reason), ("maybe", "empty_record"))

    def test_cache_avoids_second_call_and_survives_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            fake = FakeJev(FIXTURES)
            cache = ResultCache(path)
            first = screen_records(RECORDS, criteria(), fake, cache=cache)
            cache.save()
            self.assertEqual(len(fake.calls), 3)
            self.assertFalse(any(r.cached for r in first))
            reloaded = ResultCache(path)
            self.assertEqual(len(reloaded), 3)
            second = screen_records(RECORDS, criteria(), fake, cache=reloaded)
            self.assertEqual(len(fake.calls), 3)
            self.assertEqual([r.cached for r in second], [True, True, True, False])
            self.assertEqual([r.decision.label for r in second], [r.decision.label for r in first])

    def test_cache_key_changes_with_criteria(self):
        fake = FakeJev(FIXTURES)
        cache = ResultCache(Path(tempfile.mkdtemp()) / "c.json")
        screen_one(RECORDS[0], criteria(), fake, cache=cache)
        other = criteria()
        changed = other.__class__(other.review, other.inclusion[:1], other.exclusion, other.include_min, other.exclude_max, other.unknown_policy)
        screen_one(RECORDS[0], changed, fake, cache=cache)
        self.assertEqual(len(fake.calls), 2)

    def test_provider_error_propagates(self):
        fake = FakeJev({"records": {}})
        with self.assertRaises(Exception):
            screen_records(RECORDS, criteria(), fake)

    def test_resume_skips_completed_ids(self):
        fake = FakeJev(FIXTURES)
        results = screen_records(RECORDS, criteria(), fake, skip_ids={"r1", "r2"})
        self.assertEqual([r.record.id for r in results], ["r3", "r4"])
        self.assertEqual(len(fake.calls), 1)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.records = base / "records.ris"
        self.records.write_text(to_ris(RECORDS), encoding="utf-8")
        self.criteria = base / "criteria.json"
        from tests.helpers import CRITERIA_DATA

        self.criteria.write_text(json.dumps(CRITERIA_DATA), encoding="utf-8")
        self.fixtures = base / "fixtures.json"
        self.fixtures.write_text(json.dumps(FIXTURES), encoding="utf-8")
        self.out = base / "decisions.csv"
        self.human = base / "human.csv"
        self.human.write_text("id,decision\nr1,include\nr2,exclude\nr3,include\nr4,exclude\nr9,include\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def screen(self, *extra):
        return self.run_cli("screen", str(self.records), "--criteria", str(self.criteria), "--out", str(self.out),
                            "--fake", str(self.fixtures), *extra)

    def test_estimate_makes_no_call(self):
        code, out, _ = self.run_cli("estimate", str(self.records), "--criteria", str(self.criteria), "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual((data["records"], data["requests"], data["without_abstract"]), (4, 3, 1))
        self.assertGreater(data["estimated_cost_usd"], 0)

    def test_screen_resume_and_exports(self):
        export_dir = Path(self.tmp.name) / "exports"
        code, _, err = self.screen("--export-dir", str(export_dir), "--cache", str(Path(self.tmp.name) / "c.json"))
        self.assertEqual(code, 0, err)
        rows = read_decisions(self.out)
        self.assertEqual([r["decision"] for r in rows], ["include", "exclude", "maybe", "maybe"])
        self.assertEqual(completed_ids(self.out, criteria()), {"r1", "r2", "r3", "r4"})
        self.assertAlmostEqual(rows[0]["p_population"], 0.9)
        self.assertIsNone(rows[3]["inclusion_score"])
        for name in ("included.ris", "excluded.ris", "maybe.ris", "included.csv", "maybe.jsonl"):
            self.assertTrue((export_dir / name).exists(), name)
        self.assertIn("decision=include", (export_dir / "included.ris").read_text())
        # Resume: nothing new to do, file untouched apart from no duplicate rows.
        code, _, err = self.screen()
        self.assertEqual(code, 0, err)
        self.assertIn("Resuming: 4 of 4", err)
        self.assertEqual(len(read_decisions(self.out)), 4)

    def test_resume_after_partial_file(self):
        header = result_columns(criteria())
        with self.out.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=header)
            writer.writeheader()
            writer.writerow({"id": "r1", "title": "Include me", "decision": "include", "reason": "all_criteria_met"})
        code, _, err = self.screen()
        self.assertEqual(code, 0, err)
        rows = read_decisions(self.out)
        self.assertEqual([r["id"] for r in rows], ["r1", "r2", "r3", "r4"])
        self.assertIn("Screened 3 new records", err)

    def test_resume_refuses_mismatched_header(self):
        self.out.write_text("id,decision,reason\nr1,include,x\n", encoding="utf-8")
        code, _, err = self.run_cli("screen", str(self.records), "--criteria", str(self.criteria), "--out", str(self.out), "--fake", str(self.fixtures))
        self.assertEqual(code, 1)
        self.assertIn("do not match", err)

    def test_prisma_agreement_rank(self):
        self.assertEqual(self.screen()[0], 0)
        code, out, _ = self.run_cli("prisma", str(self.out), "--json")
        self.assertEqual(code, 0)
        counts = json.loads(out)
        self.assertEqual((counts["screened"], counts["included"], counts["maybe"], counts["excluded"]), (4, 1, 2, 1))
        self.assertEqual(counts["excluded_by_reason"], {"inclusion:population": 1})
        code, out, _ = self.run_cli("agreement", str(self.out), str(self.human), "--json")
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual(report["records_compared"], 4)
        self.assertEqual(report["human_labels_without_decision"], 1)
        self.assertEqual(report["confusion"], {"tp": 2, "fp": 1, "fn": 0, "tn": 1})
        self.assertEqual(report["sensitivity_recall"]["value"], 1.0)
        code, out, _ = self.run_cli("rank", str(self.out))
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 4)
        self.assertIn("r1", lines[0])
        self.assertIn("r4", lines[-1])  # unjudged record ranks last

    def test_missing_key_without_fake_is_a_clean_error(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}):
            code, _, err = self.run_cli("screen", str(self.records), "--criteria", str(self.criteria), "--out", str(self.out))
        self.assertEqual(code, 1)
        self.assertIn("TYPESAFE_API_KEY", err)


class ReportFunctionsTest(unittest.TestCase):
    def test_prisma_counts_and_reasons(self):
        rows = [
            {"id": "1", "decision": "include", "reason": "all_criteria_met"},
            {"id": "2", "decision": "exclude", "reason": "inclusion:population"},
            {"id": "3", "decision": "exclude", "reason": "inclusion:population"},
            {"id": "4", "decision": "exclude", "reason": "exclusion:animal"},
            {"id": "5", "decision": "maybe", "reason": "no_abstract"},
        ]
        counts = prisma_counts(rows)
        self.assertEqual(counts["excluded_by_reason"], {"inclusion:population": 2, "exclusion:animal": 1})
        self.assertEqual((counts["included"], counts["maybe"], counts["excluded"]), (1, 1, 3))

    def test_agreement_maybe_policy(self):
        rows = [
            {"id": "1", "decision": "maybe", "reason": "uncertain:x", "inclusion_score": 0.5},
            {"id": "2", "decision": "exclude", "reason": "inclusion:x", "inclusion_score": 0.1},
        ]
        human = {"1": True, "2": False}
        as_include = agreement_report(rows, human, maybe_as="include")
        as_exclude = agreement_report(rows, human, maybe_as="exclude")
        self.assertEqual(as_include["confusion"]["tp"], 1)
        self.assertEqual(as_exclude["confusion"]["fn"], 1)
        self.assertEqual(as_include["wss"]["records_to_read"], 1)

    def test_rank_orders_by_score_then_id(self):
        rows = [
            {"id": "b", "inclusion_score": 0.5},
            {"id": "a", "inclusion_score": 0.5},
            {"id": "c", "inclusion_score": None},
            {"id": "d", "inclusion_score": 0.9},
        ]
        self.assertEqual([r["id"] for r in rank_rows(rows)], ["d", "a", "b", "c"])


if __name__ == "__main__":
    unittest.main()
