"""Regression tests for the supplied empirical dataset."""

from __future__ import annotations

import unittest

import pandas as pd

from analysis.analyze import DEFAULT_INPUT, derive, load_and_validate, quality_checks, summarize


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.measured = load_and_validate(DEFAULT_INPUT)
        cls.derived = derive(cls.measured)
        cls.metrics = summarize(cls.derived)

    def test_dataset_shape_and_cadence(self) -> None:
        self.assertEqual(len(self.measured), 121)
        self.assertEqual(self.metrics["duration_s"], 600.0)
        self.assertEqual(self.metrics["sample_interval_s"], 5.0)

    def test_reported_results_are_reproducible(self) -> None:
        self.assertAlmostEqual(self.metrics["mean_load_voltage_V"], 5.9251736, places=6)
        self.assertAlmostEqual(self.metrics["mean_current_A"], 0.7406430, places=6)
        self.assertAlmostEqual(self.metrics["mean_load_power_W"], 4.3884215, places=6)
        self.assertAlmostEqual(self.metrics["temperature_rise_C"], 35.5, places=6)

    def test_supplied_exports_have_identical_measurements(self) -> None:
        original = pd.read_csv(DEFAULT_INPUT.parent / "buck_data.csv").rename(
            columns={"temp_C_": "temp_C"}
        )
        canonical = pd.read_csv(DEFAULT_INPUT)
        self.assertTrue(original.equals(canonical))

    def test_all_quality_checks_pass(self) -> None:
        self.assertTrue(all(quality_checks(self.derived).values()))


if __name__ == "__main__":
    unittest.main()
