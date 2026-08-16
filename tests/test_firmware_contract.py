"""Contract checks for the documented reference firmware."""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware" / "buck_logger" / "buck_logger.ino"


class FirmwareContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SKETCH.read_text(encoding="utf-8")

    def test_csv_contract_matches_canonical_dataset(self) -> None:
        self.assertIn(
            "time_s,buck_output_V,load_voltage_V,current_A,load_power_W,",
            self.source,
        )
        self.assertIn("shunt_voltage_mV,temp_C", self.source)
        self.assertIn("REPORT_PERIOD_MS = 5000", self.source)

    def test_r100_and_smoothing_are_explicit(self) -> None:
        self.assertIn("SHUNT_RESISTANCE_OHM = 0.100f", self.source)
        self.assertIn("EMA_ALPHA = 0.35f", self.source)
        self.assertIn("trimmedMean", self.source)
        self.assertIn("AVG=64", self.source)

    def test_derived_channels_are_visible_in_code(self) -> None:
        self.assertIn("shuntVoltageV / SHUNT_RESISTANCE_OHM", self.source)
        self.assertIn("filteredLoadVoltageV + shuntVoltageV", self.source)
        self.assertIn("filteredLoadVoltageV * currentA", self.source)


if __name__ == "__main__":
    unittest.main()
