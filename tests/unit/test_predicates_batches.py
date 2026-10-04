#! python3  # noqa E265

"""
    Usage from the repo root folder:

    .. code-block:: bash

        python -m unittest tests.unit.test_predicates_batches
"""

import unittest
from types import SimpleNamespace

from gpf_extraction.core.job_batch import (
    FAITHFUL_MAX_TOLERANCE_M,
    MAX_BATCHES,
    is_faithful,
    plan_batches,
    split_evenly,
)
from gpf_extraction.core.predicates import effective_predicates, reduction_note


def fit(kind, tolerance_m=0):
    return SimpleNamespace(kind=kind, tolerance_m=tolerance_m)


class TestPredicates(unittest.TestCase):
    def test_intersects_absorbs_the_predicates_that_imply_it(self):
        self.assertEqual(effective_predicates(["Intersects", "Contains"]), ["Intersects"])
        everything = ["Contains", "Intersects", "Within", "Touches", "Crosses", "Overlaps", "Equals"]
        self.assertEqual(effective_predicates(everything), ["Intersects"])

    def test_nothing_to_reduce(self):
        self.assertEqual(effective_predicates(["Contains", "Within"]), ["Contains", "Within"])
        self.assertEqual(effective_predicates(["Disjoint", "Disjoint"]), ["Disjoint"])
        self.assertEqual(effective_predicates([]), ["Intersects"])

    def test_disjoint_is_kept_with_intersects(self):
        self.assertEqual(effective_predicates(["Intersects", "Disjoint"]), ["Intersects", "Disjoint"])

    def test_note(self):
        self.assertEqual(reduction_note(["Intersects"]), "")
        self.assertTrue(reduction_note(["Intersects", "Contains", "Within"]).startswith("Contains, Within déjà inclus dans Intersects"))
        self.assertEqual(reduction_note(["Contains", "Within"]), "")


class TestBatches(unittest.TestCase):
    def test_faithful(self):
        self.assertTrue(is_faithful(None))
        self.assertTrue(is_faithful(fit("precise")))
        self.assertTrue(is_faithful(fit("simplified", FAITHFUL_MAX_TOLERANCE_M)))
        self.assertFalse(is_faithful(fit("simplified", FAITHFUL_MAX_TOLERANCE_M + 1)))
        self.assertFalse(is_faithful(fit("envelopes")))
        self.assertFalse(is_faithful(fit("bbox")))

    def test_plan_batches(self):
        # le contour est fidèle jusqu'à 10 tables par requête
        def fit_for(n):
            return fit("simplified", 25) if n <= 10 else fit("bbox")

        self.assertEqual(plan_batches(8, fit_for), 1)
        self.assertEqual(plan_batches(1, lambda n: fit("bbox")), 1)
        self.assertEqual(plan_batches(25, fit_for), 3)
        self.assertEqual(plan_batches(59, fit_for), 6)
        self.assertEqual(plan_batches(500, fit_for), 1)  # plus de MAX_BATCHES lots nécessaires
        self.assertGreaterEqual(MAX_BATCHES, 6)
        self.assertEqual(plan_batches(30, lambda n: fit("bbox")), 1)
        self.assertEqual(plan_batches(5, lambda n: None), 1)

    def test_split_evenly(self):
        self.assertEqual(split_evenly([1, 2, 3, 4, 5, 6, 7], 3), [[1, 2, 3], [4, 5], [6, 7]])
        self.assertEqual(split_evenly([1, 2], 5), [[1], [2]])
        self.assertEqual(split_evenly([], 3), [[]])
        self.assertEqual(sum(len(chunk) for chunk in split_evenly(list(range(59)), 6)), 59)


if __name__ == "__main__":
    unittest.main()
