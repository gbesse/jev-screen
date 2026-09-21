"""Purpose: Decision rule table (include / exclude / maybe with first failing reason), unjudged policy and criteria validation."""

import json
import unittest

from jev_screen.criteria import CriteriaError, build_state, parse_criteria
from jev_screen.decision import decide, decide_unjudged, inclusion_score
from jev_screen.records import Record
from tests.helpers import CRITERIA_DATA, criteria


class DecisionRuleTest(unittest.TestCase):
    def setUp(self):
        self.criteria = criteria()

    def check(self, probabilities, label, reason):
        decision = decide(self.criteria, probabilities)
        self.assertEqual((decision.label, decision.reason), (label, reason))
        return decision

    def test_table(self):
        cases = [
            ({"population": 0.9, "intervention": 0.8, "animal": 0.1}, "include", "all_criteria_met"),
            ({"population": 0.7, "intervention": 0.7, "animal": 0.3}, "include", "all_criteria_met"),  # boundaries inclusive
            ({"population": 0.2, "intervention": 0.9, "animal": 0.1}, "exclude", "inclusion:population"),
            ({"population": 0.9, "intervention": 0.3, "animal": 0.1}, "exclude", "inclusion:intervention"),
            ({"population": 0.9, "intervention": 0.9, "animal": 0.7}, "exclude", "exclusion:animal"),
            ({"population": 0.5, "intervention": 0.9, "animal": 0.1}, "maybe", "uncertain:population"),
            ({"population": 0.9, "intervention": 0.9, "animal": 0.5}, "maybe", "uncertain:animal"),
            ({"population": 0.69, "intervention": 0.9, "animal": 0.31}, "maybe", "uncertain:population"),
        ]
        for probabilities, label, reason in cases:
            with self.subTest(probabilities=probabilities):
                self.check(probabilities, label, reason)

    def test_first_failing_reason_is_in_criteria_order(self):
        # Both inclusion criteria fail and the exclusion fires: the first inclusion criterion wins.
        self.check({"population": 0.1, "intervention": 0.1, "animal": 0.95}, "exclude", "inclusion:population")
        # An uncertain inclusion before a hard exclusion failure: exclusion still decides, reason is the exclusion.
        self.check({"population": 0.5, "intervention": 0.9, "animal": 0.95}, "exclude", "exclusion:animal")

    def test_inclusion_score_is_weakest_link(self):
        self.assertAlmostEqual(inclusion_score(self.criteria, {"population": 0.9, "intervention": 0.8, "animal": 0.25}), 0.75)
        self.assertAlmostEqual(inclusion_score(self.criteria, {"population": 0.6, "intervention": 0.8, "animal": 0.1}), 0.6)

    def test_missing_probability_raises(self):
        with self.assertRaises(KeyError):
            decide(self.criteria, {"population": 0.9})

    def test_unjudged_policy(self):
        self.assertEqual(decide_unjudged(self.criteria, "no_abstract").label, "maybe")
        data = json.loads(json.dumps(CRITERIA_DATA))
        data["unknown_policy"] = "exclude"
        self.assertEqual(decide_unjudged(parse_criteria(data), "no_abstract").label, "exclude")


class CriteriaValidationTest(unittest.TestCase):
    def mutate(self, **changes):
        data = json.loads(json.dumps(CRITERIA_DATA))
        data.update(changes)
        return data

    def test_questions_are_nouls_with_criteria(self):
        questions = criteria().questions()
        self.assertEqual(list(questions), ["population", "intervention", "animal"])
        self.assertEqual(questions["population"]["type"], "noul")
        self.assertEqual(questions["population"]["criteria"]["true"], "adults with T2D")
        self.assertNotIn("criteria", questions["intervention"])

    def test_errors(self):
        bad = [
            self.mutate(inclusion=[]),
            self.mutate(inclusion=[{"id": "Bad Id", "statement": "x"}]),
            self.mutate(inclusion=[{"id": "population", "statement": ""}]),
            self.mutate(exclusion=[{"id": "population", "statement": "duplicate id"}]),
            self.mutate(thresholds={"include_min": 0.3, "exclude_max": 0.7}),
            self.mutate(thresholds={"include_min": 1.5}),
            self.mutate(unknown_policy="ask"),
            "not an object",
        ]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(CriteriaError):
                parse_criteria(data)

    def test_defaults(self):
        parsed = parse_criteria(self.mutate(thresholds={}, unknown_policy="maybe"))
        self.assertEqual((parsed.include_min, parsed.exclude_max), (0.7, 0.3))


class StateTest(unittest.TestCase):
    def test_state_holds_title_and_abstract_only(self):
        record = Record(id="x", title=" T ", abstract=" A ", authors=["Someone"], year="2020", doi="10.1/x")
        self.assertEqual(build_state(record), {"title": "T", "abstract": "A"})
        self.assertEqual(build_state(Record(id="y", title="T")), {"title": "T"})


if __name__ == "__main__":
    unittest.main()
