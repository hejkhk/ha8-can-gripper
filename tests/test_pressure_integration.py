# -*- coding: utf-8 -*-
"""Independent F103 pressure data must never become a servo control instruction."""
import os
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk

from pressure_validation import (
    parse_frame, estimate_circuit_force_g, PressureEvidence, CurveRecorder,
)
from HA8_UpperComputer import HA8UpperComputer


def frame(seq, adc, flags=0):
    return parse_frame(f"P,{seq},1234,{adc},{round(adc*3300/4095)},{flags}")


def fill_zero(state, now=10.0, baseline=110):
    for i in range(110):
        state.add(frame(i, baseline + (i % 3)-1), now - 1.1 + 0.01*i)
    return state.capture_zero(now)


class PressureIntegrationTests(unittest.TestCase):
    def test_protocol_is_existing_f103_and_force_is_theoretical(self):
        self.assertIsNone(parse_frame("12 4C 01 01 00 60"))
        self.assertEqual(frame(2, 125).sequence, 2)
        self.assertIsNone(estimate_circuit_force_g(350, -1))

    def test_zero_requires_stable_unloaded_data(self):
        s = PressureEvidence()
        with self.assertRaises(ValueError):
            s.capture_zero(10)
        self.assertAlmostEqual(fill_zero(s), 110.0, delta=1)
        self.assertIsNotNone(s.zero_noise_adc)

    def test_zero_must_be_fresh_unloaded_before_trial(self):
        s = PressureEvidence()
        ok, message = s.ready_for_trial(10.0)
        self.assertFalse(ok)
        self.assertIn("零点", message)
        fill_zero(s, now=10.0, baseline=125)
        self.assertTrue(s.ready_for_trial(10.0)[0])
        self.assertFalse(s.ready_for_trial(12.0)[0])  # stale stream
        for i in range(35):
            s.add(frame(200+i, 200), 10.1 + 0.01*i)
        ok, message = s.ready_for_trial(10.44)
        self.assertFalse(ok)
        self.assertIn("零点附近", message)
        for i in range(35):
            s.add(frame(300+i, 126), 10.5 + 0.01*i)
        self.assertTrue(s.ready_for_trial(10.84)[0])
        s.add(frame(400, 126, 1), 10.85)
        self.assertFalse(s.ready_for_trial(10.86)[0])

    def test_contact_is_evidence_only(self):
        s=PressureEvidence()
        fill_zero(s)
        for i in range(35):
            s.add(frame(i+200, 190), 10.1+i*0.01)
        result,delta=s.evidence(10.45)
        self.assertIn("压力接触证据",result)
        self.assertNotIn("已抓紧",result)
        self.assertGreater(delta,50)

    def test_stale_and_fault_frames_not_accepted(self):
        s=PressureEvidence()
        fill_zero(s)
        self.assertIsNone(s.latest(20))
        s.add(frame(1001, 4095, 2), 20.1)
        self.assertIsNone(s.latest(20.15))
        with self.assertRaises(ValueError):
            s.capture_zero(20.15)

    def test_invalid_frame_overrides_recent_valid_evidence(self):
        s=PressureEvidence()
        fill_zero(s)
        s.add(frame(1000, 190), 10.2)
        self.assertIsNotNone(s.latest(10.21))
        s.add(frame(1001, 190, 1), 10.22)
        self.assertIsNone(s.latest(10.23))

    def test_fault_prevents_contact_claim_even_if_previous_samples_are_high(self):
        s=PressureEvidence()
        fill_zero(s)
        for i in range(40):
            s.add(frame(i+150, 300), 11.0+i*0.01)
        self.assertIn("接触",s.evidence(11.4)[0])
        s.add(frame(999, 300, 1), 11.41)
        label,delta=s.evidence(11.42)
        self.assertIn("不足或已过期",label)
        self.assertIsNone(delta)

    def test_sustained_pressure_never_claims_antislip(self):
        s=PressureEvidence()
        fill_zero(s)
        for i in range(100):
            s.add(frame(i+200,250), 11.0 + i*0.01)
        label,delta=s.evidence(12.01)
        self.assertIn("持续受压",label)
        self.assertIn("未验证是否打滑",label)

    def test_theoretical_force_is_unavailable_above_nominal_sensor_rating(self):
        s=PressureEvidence()
        fill_zero(s)
        self.assertIsNotNone(s.theoretical_force_g(400))
        self.assertIsNone(s.theoretical_force_g(4090))

    def test_pairing_requires_fresh_both_channels_and_zero(self):
        s=PressureEvidence()
        c=CurveRecorder()
        c.start("海绵夹持")
        sample={"angle_deg":32.2,"current_ma":540,"status":0}
        s.add(frame(4,180), 2)
        self.assertFalse(c.add(2.04,0,sample,s,"gripping"))
        fill_zero(s)
        s.add(frame(200,180),10.3)
        self.assertTrue(c.add(10.34,0,sample,s,"gripping"))
        self.assertFalse(c.add(11.0,0,sample,s,"gripping"))
        self.assertFalse(c.add(10.35,0,dict(sample,status=4),s,"gripping"))
        self.assertEqual(len(c.rows),1)
        self.assertEqual(c.rows[0].phase,"gripping")
        self.assertEqual(c.rows[0].servo_id,0)
        self.assertGreater(c.rows[0].pressure_delta_adc,0)
        self.assertLess(c.rows[0].skew_ms,180)

    def test_scatter_and_binned_curve_are_references(self):
        s=PressureEvidence()
        fill_zero(s)
        c=CurveRecorder()
        c.start("trial")
        for i in range(120):
            t=20+i*0.09
            s.add(frame(i+1000,150+i),t)
            c.add(t+0.01,0,{"angle_deg":10+i*0.02,
                            "current_ma":200+i*8,"status":0},s,"gripping")
        scatter, trend=c.curve("adc")
        self.assertEqual(len(scatter),120)
        self.assertGreaterEqual(len(trend),5)
        self.assertGreater(trend[-1][1],trend[0][1])
        with TemporaryDirectory() as path:
            file=Path(path)/"trial.csv"
            c.export_csv(file)
            text=file.read_text(encoding="utf-8-sig")
            self.assertIn("pressure_delta_ADC",text)
            self.assertIn("theoretical_gf_unverified",text)
            self.assertIn("gripping",text)


@unittest.skipUnless(os.name=="nt" or os.environ.get("DISPLAY"),"Tk display required")
class PressureLabGuiTests(unittest.TestCase):
    def test_zero_locked_during_recording_and_cleared_after_disconnect(self):
        from unittest.mock import patch
        from types import SimpleNamespace
        from pressure_validation import PressureEvidence
        app = HA8UpperComputer()
        app.withdraw()
        try:
            panel = app.pressure_lab
            self.assertIsNone(panel.sensor.zero_adc)
            panel.link = SimpleNamespace(is_open=True, close=lambda: None)
            now = time.monotonic()
            for i in range(110):
                panel.sensor.add(frame(i, 124 + i%3-1), now-1.1+i*0.01)
            panel.capture_zero()
            previous = panel.sensor.zero_adc
            self.assertIsNotNone(previous)
            panel.recorder.start("测试")
            with patch("pressure_lab_panel.messagebox.showwarning") as warn:
                panel.capture_zero()
                warn.assert_called_once()
            self.assertEqual(panel.sensor.zero_adc, previous)
            panel.disconnect()
            self.assertIsNone(panel.sensor.zero_adc)
            self.assertIn("重新", panel.zero_text.get())
        finally:
            app.destroy()

    def test_two_tabs_and_no_commands_on_pressure_page(self):
        app=HA8UpperComputer()
        app.withdraw()
        try:
            self.assertEqual(app.nb.tab(app.tab_auto_grip,"text"),"夹爪控制")
            self.assertEqual(app.nb.tab(app.tab_pressure,"text"),"压力验证 / 曲线")
            self.assertFalse(app.pressure_lab.link.is_open)
            self.assertFalse(app.pressure_lab.recorder.active)
            self.assertIn("未连接",app.auto_grip_panel.pressure_validation_text.get())
            self.assertEqual(app.tx_ha8_count,0)
        finally:
            app.destroy()


if __name__=="__main__":
    unittest.main()
