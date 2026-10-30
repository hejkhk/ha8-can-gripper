import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from grip_force_calibration import ForceMap

class ForceModelTests(unittest.TestCase):
    def rows(self):
        return [SimpleNamespace(phase="gripping", status=0, theoretical_gf=50+25*n,
                                skew_ms=50, current_a=.25+.018*n, angle_deg=100-.4*n)
                for n in range(25)]

    def test_training_and_no_extrapolation(self):
        m=ForceMap.train(self.rows())
        self.assertIsNotNone(m.predict(.25+12*.018,100-12*.4))
        self.assertIsNone(m.predict(.1,90))
        self.assertIsNone(m.predict(.5,96,phase="idle"))
        self.assertIsNone(m.predict(.5,96,phase="stopping"))
        self.assertIsNone(m.predict(.5,96,status=4))

    def test_gap_and_persistence(self):
        m=ForceMap.train(self.rows()).with_gaps([{"angle_deg":90,"gap_mm":1},
                                                 {"angle_deg":100,"gap_mm":21}])
        self.assertAlmostEqual(m.gap_mm(95),11)
        self.assertIsNone(m.gap_mm(101))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"model.json"
            m.save(path)
            r=ForceMap.load(path)
            self.assertEqual(r.gap_mm(95),11)
            self.assertIsNone(r.as_dict()["gear"]["worm_starts"])

    def test_insufficient_span(self):
        r=self.rows()
        for p in r:p.theoretical_gf=500
        with self.assertRaises(ValueError): ForceMap.train(r)
