"""Purpose: Statistics against known values: Cohen's kappa (textbook 2x2), Wilson intervals, recall/specificity, WSS@95."""

import unittest

from jev_screen.stats import cohens_kappa, confusion, wilson_interval, work_saved_over_sampling


class KappaTest(unittest.TestCase):
    def test_textbook_two_by_two(self):
        # Classic example: 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no -> po = 0.7, pe = 0.5, kappa = 0.4.
        a = ["yes"] * 25 + ["no"] * 25
        b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15
        self.assertAlmostEqual(cohens_kappa(a, b), 0.4, places=10)

    def test_perfect_and_degenerate(self):
        self.assertEqual(cohens_kappa(["a", "b"], ["a", "b"]), 1.0)
        self.assertEqual(cohens_kappa(["a", "a"], ["a", "a"]), 1.0)
        self.assertEqual(cohens_kappa(["a", "a"], ["b", "b"]), 0.0)
        self.assertIsNone(cohens_kappa([], []))
        with self.assertRaises(ValueError):
            cohens_kappa(["a"], ["a", "b"])


class WilsonTest(unittest.TestCase):
    def test_known_values(self):
        low, high = wilson_interval(5, 10)
        self.assertAlmostEqual(low, 0.2366, places=4)
        self.assertAlmostEqual(high, 0.7634, places=4)
        low, high = wilson_interval(0, 10)
        self.assertAlmostEqual(low, 0.0, places=6)
        self.assertAlmostEqual(high, 0.2775, places=4)
        low, high = wilson_interval(10, 10)
        self.assertAlmostEqual(low, 0.7225, places=4)
        self.assertAlmostEqual(high, 1.0, places=6)

    def test_edge_cases(self):
        self.assertIsNone(wilson_interval(0, 0))
        with self.assertRaises(ValueError):
            wilson_interval(3, 2)


class ConfusionTest(unittest.TestCase):
    def test_sensitivity_specificity(self):
        predicted = [True, True, True, False, False, False]
        truth = [True, True, False, True, False, False]
        c = confusion(predicted, truth)
        self.assertEqual((c.tp, c.fp, c.fn, c.tn), (2, 1, 1, 2))
        self.assertAlmostEqual(c.sensitivity, 2 / 3)
        self.assertAlmostEqual(c.specificity, 2 / 3)
        self.assertAlmostEqual(c.precision, 2 / 3)
        self.assertAlmostEqual(c.accuracy, 4 / 6)

    def test_no_positives(self):
        c = confusion([False, False], [False, False])
        self.assertIsNone(c.sensitivity)
        self.assertEqual(c.specificity, 1.0)


class WssTest(unittest.TestCase):
    def test_hand_computed(self):
        # 10 records, 4 includes. Ranked by score they sit at positions 1, 2, 3 and 8.
        scores = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]
        truth = [True, True, True, False, False, False, False, True, False, False]
        result = work_saved_over_sampling(scores, truth, 0.95)
        # 95% of 4 = 3.8 -> all 4 needed -> read 8 records -> WSS = (10 - 8) / 10 - 0.05 = 0.15
        self.assertEqual(result.screened, 8)
        self.assertAlmostEqual(result.wss, 0.15)
        # With the includes at the top, reading 4 of 10 gives WSS = 0.6 - 0.05 = 0.55
        truth_top = [True, True, True, True] + [False] * 6
        self.assertAlmostEqual(work_saved_over_sampling(scores, truth_top, 0.95).wss, 0.55)

    def test_ties_are_pessimistic(self):
        scores = [0.5, 0.5, 0.5]
        truth = [True, False, False]
        result = work_saved_over_sampling(scores, truth, 0.95)
        self.assertEqual(result.screened, 3)  # equal scores: the include is assumed to come last

    def test_no_positives_is_undefined(self):
        self.assertIsNone(work_saved_over_sampling([0.1, 0.2], [False, False]).wss)


if __name__ == "__main__":
    unittest.main()
