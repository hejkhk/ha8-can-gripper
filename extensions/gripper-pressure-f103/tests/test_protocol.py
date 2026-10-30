import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PC_UpperComputer"))
from protocol import parse_frame, validate_points, estimate_force_g

class FrameTests(unittest.TestCase):
    def test_valid(self):
        p = parse_frame("P,12,430,2048,1650,0\r\n")
        self.assertEqual((p.sequence, p.adc, p.voltage_mv), (12, 2048, 1650))

    def test_invalid(self):
        for text in ["READY", "P,4,5", "P,1,2,4096,3300,0", "P,1,2,0,-2,0", "P,1,2,0,1,no"]:
            self.assertIsNone(parse_frame(text))

    def test_linear_calibration(self):
        c = [{"g":0,"adc":100},{"g":500,"adc":1500},{"g":1000,"adc":3000}]
        self.assertTrue(validate_points(c))
        self.assertAlmostEqual(estimate_force_g(2250, c), 750)
        self.assertEqual(estimate_force_g(50, c), 0.0)
        self.assertEqual(estimate_force_g(100, c), 0.0)
        self.assertIsNone(estimate_force_g(3500, c))

    def test_reversed_polarity(self):
        c = [{"g":0,"adc":3000},{"g":1000,"adc":1000}]
        self.assertTrue(validate_points(c))
        self.assertAlmostEqual(estimate_force_g(2000, c), 500)
        self.assertEqual(estimate_force_g(3200, c), 0.0)
        self.assertIsNone(estimate_force_g(500, c))

    def test_first_nonzero_boundary(self):
        c = [{"g":50,"adc":300},{"g":500,"adc":1700}]
        self.assertEqual(estimate_force_g(300, c), 50.0)
        self.assertIsNone(estimate_force_g(200, c))

    def test_nonmonotonic_rejected(self):
        self.assertFalse(validate_points([{"g":0,"adc":500},{"g":100,"adc":400},{"g":200,"adc":600}]))

if __name__ == "__main__":
    unittest.main()

class ManufacturerCurveTests(unittest.TestCase):
    def test_points_exact(self):
        from protocol import manufacturer_conductance
        expected = [(0, 0), (50, 0.0063), (100, .0111), (200, .0204),
                    (500, .0556), (1000, .1020), (2000, .2000)]
        for f, g in expected:
            self.assertAlmostEqual(manufacturer_conductance(f), g)
        self.assertIsNone(manufacturer_conductance(2001))

    def test_one_reference_calibration(self):
        from protocol import estimate_factory_force_g, manufacturer_conductance
        # 实测无载 100 ADC；500gf 时 1600 ADC，则参考电导=0.0556 1/kΩ。
        self.assertEqual(estimate_factory_force_g(100, 100, 1600, 500), 0.0)
        self.assertAlmostEqual(estimate_factory_force_g(1600, 100, 1600, 500), 500.0)
        adc_1000 = 100 + (1600 - 100) * manufacturer_conductance(1000) / manufacturer_conductance(500)
        self.assertAlmostEqual(estimate_factory_force_g(adc_1000, 100, 1600, 500), 1000.0)
        self.assertEqual(estimate_factory_force_g(90, 100, 1600, 500), 0.0)
        self.assertGreater(estimate_factory_force_g(4095, 100, 1600, 500), 1000)

    def test_reverse_slope(self):
        from protocol import estimate_factory_force_g
        self.assertAlmostEqual(estimate_factory_force_g(2000, 3500, 2000, 500), 500)
        self.assertEqual(estimate_factory_force_g(3600, 3500, 2000, 500), 0)

    def test_cannot_convert_without_reference(self):
        from protocol import estimate_factory_force_g
        self.assertIsNone(estimate_factory_force_g(1744, None, None, None))
        self.assertIsNone(estimate_factory_force_g(1744, 100, 101, 500))
        self.assertIsNone(estimate_factory_force_g(1744, 100, 1800, 0))
        self.assertIsNone(estimate_factory_force_g(1744, 100, 1800, 2100))


class CircuitModelTests(unittest.TestCase):
    def test_rf_validation(self):
        from protocol import feedback_resistor_valid
        for value in (150, "150", 0.001, 300):
            self.assertTrue(feedback_resistor_valid(value))
        for value in (None, "", "bad", float('nan'), 0, -5, 301):
            self.assertFalse(feedback_resistor_valid(value))

    def test_manual_theoretical_reference_points(self):
        from protocol import estimate_circuit_force_g, MANUFACTURER_POINTS
        rf_kohm = 150.0
        for force_g, conductance in MANUFACTURER_POINTS:
            voltage = 0.1 * (1 + rf_kohm * conductance)
            adc = voltage / 3.3 * 4095
            f = estimate_circuit_force_g(adc, rf_kohm)
            self.assertIsNotNone(f)
            self.assertAlmostEqual(f, force_g, delta=1e-6)

    def test_current_offset_and_nonextrapolation(self):
        from protocol import estimate_circuit_force_g
        rf = 150.0
        z = 137.0
        self.assertEqual(estimate_circuit_force_g(z, rf, z), 0)
        adc500 = z + (0.1 * rf * 0.0556) / 3.3 * 4095
        self.assertAlmostEqual(estimate_circuit_force_g(adc500, rf, z), 500, delta=1e-6)
        self.assertIsNone(estimate_circuit_force_g(4095, 150, z))
        self.assertIsNone(estimate_circuit_force_g(123, None, z))

    def test_300k_cannot_cover_2kg(self):
        self.assertGreater(0.1 * (1 + 300 / 5), 3.3)
        from protocol import estimate_circuit_force_g
        self.assertLess(estimate_circuit_force_g(4095, 300), 1200)
