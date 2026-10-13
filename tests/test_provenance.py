"""Regression tests for stale resume and synthetic/live provider boundaries."""

import copy
import csv
import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from jev_screen import (
    FakeJev,
    JevClient,
    ResultCache,
    protocol_snapshot,
    record_fingerprint,
)
from jev_screen.cli import main
from jev_screen.client import request_key
from jev_screen.provenance import MESSAGES, ProtocolError, ScreeningContext, fingerprint
from jev_screen.records import Record, to_ris
from jev_screen.screening import (
    completed_ids,
    read_decisions,
    result_columns,
    result_row,
    screen_one,
    screen_records,
)
from tests.helpers import CRITERIA_DATA, criteria
from tests.test_screening import FIXTURES, RECORDS


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "decisions.csv"
        self.provider = FakeJev(copy.deepcopy(FIXTURES))
        self.criteria = criteria()
        results = screen_records(RECORDS, self.criteria, self.provider)
        self.rows = [result_row(r, self.criteria) for r in results]
        self.write(self.rows)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rows):
        with self.path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=result_columns(self.criteria))
            writer.writeheader()
            writer.writerows(rows)

    def done(self, criteria_=None, records=None, provider=None, **kwargs):
        return completed_ids(
            self.path,
            criteria_ or self.criteria,
            records=records if records is not None else RECORDS,
            provider=provider or self.provider,
            **kwargs,
        )

    def test_identical_context_and_added_records_resume(self):
        self.assertEqual(self.done(), {"r1", "r2", "r3", "r4"})
        added = RECORDS + [Record(id="new", title="Unjudged")]
        self.assertEqual(self.done(records=added), {"r1", "r2", "r3", "r4"})
        self.assertEqual(
            self.done(records=list(reversed(RECORDS))), {"r1", "r2", "r3", "r4"}
        )

    def test_same_criterion_ids_changed_semantics_or_policy_refuse_resume(self):
        first = self.criteria.inclusion[0]
        variants = [
            replace(
                self.criteria,
                inclusion=(replace(first, statement="Different eligibility"),)
                + self.criteria.inclusion[1:],
            ),
            replace(
                self.criteria,
                inclusion=(replace(first, true_description="Different evidence"),)
                + self.criteria.inclusion[1:],
            ),
            replace(self.criteria, include_min=0.95),
            replace(self.criteria, exclude_max=0.2),
            replace(self.criteria, unknown_policy="exclude"),
            replace(self.criteria, review="Another protocol"),
        ]
        for changed in variants:
            self.assertEqual(result_columns(changed), result_columns(self.criteria))
            with self.subTest(changed=changed), self.assertRaises(ProtocolError) as err:
                self.done(criteria_=changed)
            self.assertEqual(err.exception.code, "protocol")

    def test_title_only_model_and_fixture_changes_refuse_resume(self):
        with self.assertRaises(ProtocolError):
            self.done(title_only=True)
        changed = FakeJev(copy.deepcopy(FIXTURES), model="jev-preview")
        with self.assertRaises(ProtocolError):
            self.done(provider=changed)
        changed = FakeJev(copy.deepcopy(FIXTURES))
        changed.fixtures["records"]["Include me"]["population"] = 0.1
        with self.assertRaises(ProtocolError):
            self.done(provider=changed)

    def test_changed_text_or_bibliography_and_removed_ids_refuse_resume(self):
        for field, value in [
            ("title", "Changed title"),
            ("abstract", "Changed abstract"),
            ("doi", "10.test/example"),
            ("authors", ["Another author"]),
            ("year", "2025"),
        ]:
            records = copy.deepcopy(RECORDS)
            setattr(records[0], field, value)
            with self.subTest(field=field), self.assertRaises(ProtocolError) as err:
                self.done(records=records)
            self.assertEqual(err.exception.code, "record")
        with self.assertRaises(ProtocolError):
            self.done(records=RECORDS[1:])
        records = copy.deepcopy(RECORDS)
        records[3].abstract = "Now there is evidence"
        with self.assertRaises(ProtocolError):
            self.done(records=records)

    def test_corruption_duplicate_rows_and_interrupted_tail_fail_closed(self):
        changed = copy.deepcopy(self.rows)
        changed[0]["decision"] = "exclude"
        self.write(changed)
        with self.assertRaises(ProtocolError) as err:
            self.done()
        self.assertEqual(err.exception.code, "row")
        self.write(self.rows + [self.rows[0]])
        with self.assertRaises(ProtocolError):
            self.done()
        self.write(self.rows)
        with self.path.open("a") as f:
            f.write("tail,incomplete\n")
        with self.assertRaises(ProtocolError):
            self.done()

    def test_legacy_rows_or_missing_context_not_trusted(self):
        with self.assertRaises(ProtocolError) as err:
            completed_ids(self.path, self.criteria)
        self.assertEqual(err.exception.code, "context")
        self.path.write_text("id,decision,reason\nr1,include,x\n")
        with self.assertRaises(ProtocolError) as err:
            self.done()
        self.assertEqual(err.exception.code, "header")

    def test_user_text_preserved_and_credentials_absent_from_snapshots(self):
        changed = replace(
            self.criteria, review="Revisión del usuario — ne pas traduire"
        )
        client = JevClient(
            api_key="sentinel-secret",
            endpoint="https://example.test/v1/systemone?token=another-sentinel",
        )
        data = protocol_snapshot(changed, client)
        encoded = json.dumps(data, ensure_ascii=False)
        self.assertIn(changed.review, encoded)
        self.assertNotIn("sentinel", encoded)
        self.assertNotIn("example.test", encoded)
        self.assertEqual(data["provider"]["kind"], "api")

    def test_mutation_of_a_record_after_screening_cannot_emit_a_false_receipt(self):
        record = copy.deepcopy(RECORDS[0])
        result = screen_one(record, self.criteria, self.provider)
        record.abstract = "changed after judgement"
        with self.assertRaises(ProtocolError):
            result_row(result, self.criteria)

    def test_cache_separates_fixtures_and_api_even_for_same_request(self):
        cache = ResultCache(Path(self.tmp.name) / "cache.json")
        first = screen_one(RECORDS[0], self.criteria, self.provider, cache=cache)

        def opener(request, timeout):
            body = json.loads(request.data)
            return (
                200,
                {},
                json.dumps(
                    {
                        "model": body["model"],
                        "answers": {
                            k: {"type": "noul", "noul": 0.1} for k in body["questions"]
                        },
                        "usage": {"input_tokens": 10, "output_tokens": 0},
                    }
                ).encode(),
            )

        client = JevClient(api_key="synthetic", opener=opener)
        second = screen_one(RECORDS[0], self.criteria, client, cache=cache)
        self.assertEqual(first.decision.label, "include")
        self.assertEqual(second.decision.label, "exclude")
        self.assertEqual(client.calls, 1)
        self.assertEqual(first.request_key, second.request_key)
        self.assertNotEqual(first.protocol_sha256, second.protocol_sha256)
        third = screen_one(RECORDS[0], self.criteria, client, cache=cache)
        self.assertTrue(third.cached)
        self.assertEqual(client.calls, 1)

    def test_fixture_changes_recompute_answers_but_threshold_changes_reuse_raw_answers(
        self,
    ):
        cache = ResultCache(Path(self.tmp.name) / "cache.json")
        first = screen_one(RECORDS[0], self.criteria, self.provider, cache=cache)
        changed = replace(self.criteria, include_min=0.95)
        second = screen_one(RECORDS[0], changed, self.provider, cache=cache)
        self.assertTrue(second.cached)
        self.assertEqual(second.decision.label, "maybe")
        self.assertNotEqual(first.protocol_sha256, second.protocol_sha256)
        altered = FakeJev(copy.deepcopy(FIXTURES))
        altered.fixtures["records"]["Include me"]["population"] = 0.1
        third = screen_one(RECORDS[0], self.criteria, altered, cache=cache)
        self.assertFalse(third.cached)
        self.assertEqual(third.decision.label, "exclude")
        self.assertEqual(len(altered.calls), 1)

    def test_old_unscoped_cache_is_not_promoted(self):
        cache = ResultCache(Path(self.tmp.name) / "cache.json")
        result = screen_one(RECORDS[0], self.criteria, self.provider)
        cache.put(
            result.request_key,
            type(
                "Result",
                (),
                {
                    "model": result.model,
                    "answers": {
                        cid: {"type": "noul", "noul": 0.01} for cid in self.criteria.ids
                    },
                    "usage": {"input_tokens": 1, "output_tokens": 0},
                },
            )(),
        )
        again = screen_one(RECORDS[0], self.criteria, self.provider, cache=cache)
        self.assertFalse(again.cached)
        self.assertEqual(again.decision.label, "include")

    def test_corrupted_cached_model_or_probability_is_refused(self):
        for field, value in [
            ("model", "wrong"),
            ("probability", float("nan")),
            ("probability", True),
        ]:
            cache = ResultCache(Path(self.tmp.name) / "cache.json")
            screen_one(RECORDS[0], self.criteria, self.provider, cache=cache)
            entry = next(iter(cache._entries.values()))
            if field == "model":
                entry["model"] = value
            else:
                entry["answers"]["population"]["noul"] = value
            with self.assertRaises(ProtocolError) as err:
                screen_one(RECORDS[0], self.criteria, self.provider, cache=cache)
            self.assertEqual(err.exception.code, "cache")

    def test_custom_provider_requires_explicit_stable_identity(self):
        class Custom:
            model = "jev-1.13.0"

        with self.assertRaises(ProtocolError):
            protocol_snapshot(self.criteria, Custom())
        p = Custom()
        p.resume_identity = {"rubric": "v1"}
        first = protocol_snapshot(self.criteria, p)
        p.resume_identity = {"rubric": "v2"}
        self.assertNotEqual(first, protocol_snapshot(self.criteria, p))

    def test_demo_all_languages(self):
        from examples.protocol_resume import run, MESSAGES as DEMO_MESSAGES

        for lang in ("fr", "en", "es"):
            with redirect_stdout(io.StringIO()):
                summary = run(lang)
            self.assertEqual(summary["message"], DEMO_MESSAGES[lang])
            self.assertTrue(summary["stale_resume_rejected"])
            self.assertEqual(summary["after"]["decision"], "maybe")

    def test_empty_output_requires_no_context_and_duplicate_input_is_rejected(self):
        self.path.write_text("")
        self.assertEqual(completed_ids(self.path, self.criteria), set())
        with self.assertRaises(ValueError):
            screen_records(RECORDS + [RECORDS[0]], self.criteria, self.provider)


class ReceiptCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.records = self.root / "records.ris"
        self.records.write_text(to_ris(RECORDS))
        self.criteria = self.root / "criteria.json"
        self.criteria.write_text(json.dumps(CRITERIA_DATA))
        self.fixtures = self.root / "fixtures.json"
        self.fixtures.write_text(json.dumps(FIXTURES))
        self.out = self.root / "decisions.csv"
        self.receipt = self.root / "receipt.json"
        self.args = [
            "screen",
            str(self.records),
            "--criteria",
            str(self.criteria),
            "--out",
            str(self.out),
            "--fake",
            str(self.fixtures),
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(self.args + list(extra))
        return code, err.getvalue()

    def test_private_receipt_matches_csv_and_has_no_abstracts(self):
        code, err = self.run_cli("--receipt", str(self.receipt))
        self.assertEqual(code, 0, err)
        data = json.loads(self.receipt.read_text())
        self.assertEqual(
            data["decisions_csv_sha256"],
            hashlib.sha256(self.out.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            data["protocol_sha256"], read_decisions(self.out)[0]["protocol_sha256"]
        )
        self.assertEqual(data["counts"]["screened"], 4)
        self.assertIsNone(data["signature"])
        self.assertNotIn(RECORDS[0].abstract, self.receipt.read_text())
        self.assertEqual(self.receipt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(data["protocol"]["provider"]["kind"], "fixtures")

    def test_reference_manager_exports_keep_protocol_identity(self):
        export_dir = self.root / "exports"
        code, err = self.run_cli("--export-dir", str(export_dir))
        self.assertEqual(code, 0, err)
        original = read_decisions(self.out)[0]
        ris = (export_dir / "included.ris").read_text()
        self.assertIn("protocol_sha256=" + original["protocol_sha256"], ris)
        self.assertIn("record_sha256=" + original["record_sha256"], ris)
        data = json.loads((export_dir / "included.jsonl").read_text().splitlines()[0])
        self.assertEqual(data["protocol_sha256"], original["protocol_sha256"])
        with (export_dir / "included.csv").open() as handle:
            exported = next(csv.DictReader(handle))
        self.assertEqual(exported["input_tokens"], original["input_tokens"])
        self.assertEqual(exported["cached"], original["cached"])

    def test_receipt_collision_or_output_alias_is_rejected_before_calls(self):
        self.receipt.write_text("USER FILE")
        with patch.object(
            FakeJev, "ask", side_effect=AssertionError("unexpected call")
        ):
            self.assertEqual(self.run_cli("--receipt", str(self.receipt))[0], 1)
            self.assertEqual(self.run_cli("--receipt", str(self.out))[0], 1)
            self.assertEqual(self.run_cli("--receipt", str(self.records))[0], 1)
        self.assertEqual(self.receipt.read_text(), "USER FILE")
        self.assertFalse(self.out.exists())

    def test_cli_protocol_change_leaves_previous_csv_untouched_and_makes_no_call(self):
        self.assertEqual(self.run_cli()[0], 0)
        before = self.out.read_bytes()
        data = copy.deepcopy(CRITERIA_DATA)
        data["thresholds"]["include_min"] = 0.95
        self.criteria.write_text(json.dumps(data))
        with patch.object(
            FakeJev, "ask", side_effect=AssertionError("unexpected call")
        ):
            code, err = self.run_cli("--receipt", str(self.receipt))
        self.assertEqual(code, 1)
        self.assertIn(MESSAGES["protocol"], err)
        self.assertEqual(self.out.read_bytes(), before)
        self.assertFalse(self.receipt.exists())

    def test_explicit_new_output_reapplies_changed_thresholds_from_cache(self):
        cache = self.root / "cache.json"
        self.assertEqual(self.run_cli("--cache", str(cache))[0], 0)
        data = copy.deepcopy(CRITERIA_DATA)
        data["thresholds"]["include_min"] = 0.95
        self.criteria.write_text(json.dumps(data))
        self.args[self.args.index("--out") + 1] = str(self.root / "changed.csv")
        with patch.object(
            FakeJev, "ask", side_effect=AssertionError("unexpected call")
        ):
            code, err = self.run_cli("--cache", str(cache))
        self.assertEqual(code, 0, err)
        rows = read_decisions(self.root / "changed.csv")
        self.assertEqual(rows[0]["decision"], "maybe")
        self.assertEqual(rows[0]["cached"], "1")

    def test_failed_provider_removes_incomplete_receipt_and_resume_recovers(self):
        with patch.object(FakeJev, "ask", side_effect=ValueError("synthetic failure")):
            self.assertEqual(self.run_cli("--receipt", str(self.receipt))[0], 1)
        self.assertFalse(self.receipt.exists())
        code, err = self.run_cli("--receipt", str(self.receipt))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(read_decisions(self.out)), 4)


if __name__ == "__main__":
    unittest.main()
