import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from grip_estimator import (
    GripDetector, GripSample, GripSettings, GripState,
    REFERENCE_DYNAMIC_POINTS, parse_curve, dynamic_torque_reference,
)


class TorqueTests(unittest.TestCase):
    def test_bounded_curve_interpolation(self):
        self.assertAlmostEqual(dynamic_torque_reference(.45, 100), .625)
        self.assertIsNone(dynamic_torque_reference(.20, 100))
        self.assertIsNone(dynamic_torque_reference(.80, 100))
        self.assertIsNone(dynamic_torque_reference(.50, 0))

    def test_invalid_curve(self):
        for spec in ('0.5:0.8,0.3:0.6', '0.2:0.4', 'nan:1,2:3', '0.5:-0.1,0.6:1'):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                parse_curve(spec)


class GripTests(unittest.TestCase):
    def make(self, **config):
        args = dict(stable_seconds=.4, minimum_travel_deg=1,
                    low_speed_dps=2, baseline_a=.1, contact_delta_a=.2,
                    minimum_grip_current_a=.5, maximum_safe_current_a=1.8,
                    valid_angle_min=0, valid_angle_max=20, stale_seconds=2.5)
        args.update(config)
        return GripDetector(GripSettings(**args))

    def series(self, det, points, status=0):
        out = None
        for t, a, i in points:
            out = det.observe(GripSample(t, a, i, status))
        return out

    def test_never_claims_verified_and_requires_arming(self):
        d = self.make()
        self.series(d, [(0, 0, .1), (.1, 2, .2), (.2, 4, .3), (.3, 4, .6),
                        (.4, 4, .6), (.5, 4, .6), (.6, 4, .6), (.7, 4, .6),
                        (.8, 4, .6), (.9, 4, .6), (1.1, 4, .6)])
        self.assertEqual(d.state, GripState.IDLE)
        d.arm()
        out = self.series(d, [(0, 0, .1), (.1, 2, .2), (.2, 4, .3),
                              (.3, 4, .6), (.4, 4, .6), (.5, 4, .6),
                              (.6, 4, .6), (.7, 4, .6), (.8, 4, .6),
                              (.9, 4, .6), (1., 4, .6), (1.2, 4, .6),
                              (1.4, 4, .6)])
        self.assertEqual(out.state, GripState.CANDIDATE)
        self.assertIn('不能证明', out.note)

    def test_missing_angle_band_disallows_candidate(self):
        d = self.make(valid_angle_min=None, valid_angle_max=None)
        d.arm()
        out = self.series(d, [(0,0,.1),(.1,3,.1),(.2,3,.7),(.3,3,.7),(.4,3,.7),
                              (.5,3,.7),(.6,3,.7),(.7,3,.7),(.8,3,.7),
                              (.9,3,.7),(1.1,3,.7),(1.3,3,.7)])
        self.assertEqual(out.state, GripState.UNVERIFIED)

    def test_stall_status_preempts_grip(self):
        d = self.make()
        d.arm()
        d.observe(GripSample(0, 0, .1))
        out = d.observe(GripSample(.1, 4, .8, status_bits=4))
        self.assertEqual(out.state, GripState.FAULT)
        # Fault remains latched even if fault bits drop for the next sample.
        recovered = d.observe(GripSample(.2, 4, .5, status_bits=0))
        self.assertEqual(recovered.state, GripState.FAULT)

    def test_beyond_angle_band_fails(self):
        d = self.make(valid_angle_min=0, valid_angle_max=5)
        d.arm()
        out = self.series(d, [(0, 0, .1), (.1, 8, .3), (.2, 8, .7),
                              (.3, 8, .7), (.4, 8, .7), (.5, 8, .7),
                              (.6, 8, .7), (.7, 8, .7), (.9, 8, .7),
                              (1.1, 8, .7), (1.3, 8, .7)])
        self.assertEqual(out.state, GripState.FAULT)

    def test_wrong_direction_no_contact(self):
        d = self.make(closing_direction=-1)
        d.arm()
        self.series(d, [(0, 0, .1), (.1, 4, .2), (.2, 4, .6), (.3, 4, .6),
                        (.4, 4, .6), (.5, 4, .6), (.6, 4, .6), (.9, 4, .6)])
        self.assertEqual(d.state, GripState.CLOSING)

    def test_stale(self):
        d = self.make(stale_seconds=.8)
        d.arm()
        d.observe(GripSample(0.0, 0, .1))
        self.assertEqual(d.check_stale(1.0).state, GripState.STALE)


if __name__ == '__main__':
    unittest.main()