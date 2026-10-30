# -*- coding: utf-8 -*-
"""CSV export, time labels, guarded one-degree steps: offline deterministic tests."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from calibration_capture import CalibrationRun, StepMotionState
from pressure_protocol import PressureFrame


class CalibrationCsvTests(unittest.TestCase):
    def test_four_separate_csvs_preserve_all_raw_f103_and_ha8_samples(self):
        run=CalibrationRun("试验 1",123,0,start_mono=50.0,start_unix=1730000000.0)
        for i in range(100):
            frame=PressureFrame(i,1000+10*i,123+i,100+i,0)
            run.pressure(frame,50.01*i,100+i)
        for i in range(10):
            run.ha8(0,{"angle_deg":90-i*.1,"current_ma":500+i,
                "voltage_mv":12000,"power_mw":100,"status":0,
                "temperature_adc":100,"turn":0},50.1*i,"gripping",89)
        run.event("step_command",at=50.5,servo_id=0,target_deg=89)
        run.stop()
        with tempfile.TemporaryDirectory() as tmp:
            folder=run.export([],tmp)
            for name in ("01_pressure_f103.csv","02_ha8_servo.csv",
                         "03_step_events.csv","04_paired_curve.csv","metadata.json"):
                self.assertTrue((folder/name).is_file())
            with (folder/"01_pressure_f103.csv").open(encoding="utf-8-sig",newline="") as fh:
                pressure=list(csv.DictReader(fh))
            with (folder/"02_ha8_servo.csv").open(encoding="utf-8-sig",newline="") as fh:
                ha8=list(csv.DictReader(fh))
            self.assertEqual(len(pressure),100)
            self.assertEqual(len(ha8),10)
            self.assertEqual(pressure[0]["zero_adc"],"123.0")
            self.assertEqual(pressure[10]["seq"],"10")
            self.assertIn("pc_time_utc",pressure[0])
            self.assertEqual(pressure[0]["f103_uptime_ms"],"1000")
            self.assertEqual(ha8[0]["servo_id"],"0")
            self.assertAlmostEqual(float(pressure[50]["elapsed_s"]),.5)
            info=json.loads((folder/"metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(info["counts"]["pressure"],100)
            self.assertTrue(info["force_values_are_unvalidated"])
            self.assertEqual(folder,run.export([],tmp))
            with self.assertRaises(ValueError):
                run2=CalibrationRun("x",0,0,start_mono=0,start_unix=0)
                run2.export([],tmp)

    def test_error_flags_are_not_lost_and_stopping_disables_new_samples(self):
        run=CalibrationRun("faults",123,0,start_mono=10,start_unix=1730000000)
        run.pressure(PressureFrame(1,1000,4095,3300,2),10.1,None)
        self.assertEqual(run.pressure_rows[0]["flags"],2)
        self.assertEqual(run.pressure_rows[0]["force_gf_theoretical"],"")
        run.stop()
        run.pressure(PressureFrame(2,1010,125,101,0),10.2,None)
        self.assertEqual(len(run.pressure_rows),1)


class OneDegreeStateTests(unittest.TestCase):
    def test_duplicate_command_blocked_until_two_stable_feedbacks(self):
        step=StepMotionState()
        step.begin(29.0,10.0)
        with self.assertRaises(RuntimeError):
            step.begin(28.0,10.1)
        self.assertEqual(step.observe(29.8,10.1,0),"moving")
        self.assertEqual(step.observe(29.1,10.2,0),"moving")
        self.assertEqual(step.observe(29.0,10.3,0),"complete")
        self.assertFalse(step.pending)
        step.begin(28,11)
        self.assertEqual(step.observe(28,14.2,0),"timeout")
        step.clear()
        step.begin(27,15)
        self.assertEqual(step.observe(27,15.1,4),"fault")


if __name__=="__main__":
    unittest.main()
