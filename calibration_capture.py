# -*- coding: utf-8 -*-
"""Timestamp-preserving, read-only experiment logging and step-motion bookkeeping.

No hardware is controlled by this module. FSR readings are *estimated* forces,
not independently calibrated load-cell results.
"""
from __future__ import annotations

import csv
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parent / "calibration_records"
MAX_RAW = 180000  # ~30 minutes at 100Hz, bounded memory


def utc_stamp(unix_s):
    return datetime.fromtimestamp(unix_s, tz=timezone.utc).isoformat(timespec="milliseconds")


class CalibrationRun:
    """Four files with distinct sampling clocks: F103, HA8, steps and paired rows."""

    def __init__(self, trial, zero_adc, servo_id, start_mono=None, start_unix=None):
        self.trial = str(trial or "experiment").strip()[:48]
        self.zero_adc = float(zero_adc)
        self.servo_id = int(servo_id)
        self.start_mono = time.monotonic() if start_mono is None else float(start_mono)
        self.start_unix = time.time() if start_unix is None else float(start_unix)
        self.active = True
        self.pressure_rows = []
        self.ha8_rows = []
        self.events = []
        self.exported = None

    def timestamp(self, at):
        elapsed = max(0.0, float(at) - self.start_mono)
        unix_s = self.start_unix + elapsed
        return {"pc_time_utc":utc_stamp(unix_s),
                "pc_unix_ms":round(unix_s * 1000, 3),
                "elapsed_s":round(elapsed, 6)}

    def _append(self, group, row):
        if not self.active:
            return
        if len(group) >= MAX_RAW:
            self.active = False
            raise OverflowError("实验采样超出上限，请立即完成并导出")
        group.append(row)

    def pressure(self, frame, at, force_gf):
        stamp = self.timestamp(at)
        gf = float(force_gf) if force_gf is not None else None
        if gf is not None and not math.isfinite(gf):
            gf = None
        self._append(self.pressure_rows, {
            **stamp, "trial":self.trial, "source":"F103",
            "seq":int(frame.sequence), "f103_uptime_ms":int(frame.uptime_ms),
            "adc_raw":int(frame.adc), "voltage_mV":int(frame.voltage_mv),
            "zero_adc":self.zero_adc, "delta_adc":round(int(frame.adc)-self.zero_adc, 3),
            "force_gf_theoretical":round(gf, 4) if gf is not None else "",
            "force_N_theoretical":round(gf*0.00980665, 6) if gf is not None else "",
            "within_nominal_1kg":int(gf is not None and 0 <= gf <= 1000),
            "flags":int(frame.status),
        })

    def ha8(self, sid, fields, at, phase, step_target=None):
        self._append(self.ha8_rows, {
            **self.timestamp(at), "trial":self.trial, "source":"HA8",
            "servo_id":int(sid), "angle_deg":float(fields["angle_deg"]),
            "current_mA":int(fields["current_ma"]),
            "current_A":float(fields["current_ma"])/1000.0,
            "voltage_mV":int(fields.get("voltage_mv", 0)),
            "power_mW":int(fields.get("power_mw", 0)),
            "temperature_ADC":fields.get("temperature_adc", ""),
            "turn":fields.get("turn", ""),
            "status":int(fields["status"]),
            "phase":str(phase or "idle"),
            "step_target_deg":"" if step_target is None else float(step_target),
        })

    def event(self, label, at=None, **details):
        if not self.active:
            return
        t = time.monotonic() if at is None else float(at)
        self._append(self.events, {**self.timestamp(t),
                                  "trial":self.trial,"event":str(label),
                                  "details_json":json.dumps(details,ensure_ascii=False,sort_keys=True)})

    def stop(self):
        self.active = False

    @staticmethod
    def _write_csv(path, headers, rows):
        with path.open("w",newline="",encoding="utf-8-sig") as handle:
            out=csv.DictWriter(handle,fieldnames=headers,extrasaction="ignore")
            out.writeheader()
            out.writerows(rows)

    def export(self, paired_rows, root=DATA_ROOT):
        """Create one unique run directory; leave existing files untouched."""
        if self.active:
            raise ValueError("请先完成采集再导出")
        if self.exported is not None:
            return self.exported
        root=Path(root)
        root.mkdir(parents=True,exist_ok=True)
        stem = datetime.fromtimestamp(self.start_unix).strftime("run_%Y%m%d_%H%M%S_%f")
        folder=root/stem
        folder.mkdir(exist_ok=False)
        self._write_csv(folder/"01_pressure_f103.csv",
            ["pc_time_utc","pc_unix_ms","elapsed_s","trial","source","seq","f103_uptime_ms",
             "adc_raw","voltage_mV","zero_adc","delta_adc","force_gf_theoretical",
             "force_N_theoretical","within_nominal_1kg","flags"],self.pressure_rows)
        self._write_csv(folder/"02_ha8_servo.csv",
            ["pc_time_utc","pc_unix_ms","elapsed_s","trial","source","servo_id","angle_deg",
             "current_mA","current_A","voltage_mV","power_mW","temperature_ADC","turn",
             "status","phase","step_target_deg"],self.ha8_rows)
        self._write_csv(folder/"03_step_events.csv",
            ["pc_time_utc","pc_unix_ms","elapsed_s","trial","event","details_json"],self.events)
        paired = []
        for p in paired_rows:
            paired.append({
                "pc_time_utc":utc_stamp(p.pc_time_s),
                "pc_unix_ms":round(p.pc_time_s * 1000,3),
                "trial":p.trial, "servo_id":p.servo_id,"current_A":p.current_a,
                "angle_deg":p.angle_deg,"phase":p.phase,"ha8_status":p.status,
                "pressure_adc":p.pressure_adc,"pressure_delta_adc":p.pressure_delta_adc,
                "pressure_mV":p.pressure_mv,
                "theoretical_gf_unverified":"" if p.theoretical_gf is None else p.theoretical_gf,
                "pressure_seq":p.pressure_seq,"skew_ms":p.skew_ms
            })
        self._write_csv(folder/"04_paired_curve.csv",
            ["pc_time_utc","pc_unix_ms","trial","servo_id","current_A","angle_deg","phase",
             "ha8_status","pressure_adc","pressure_delta_adc","pressure_mV",
             "theoretical_gf_unverified","pressure_seq","skew_ms"],paired)
        (folder/"metadata.json").write_text(json.dumps({
            "schema":1,"trial":self.trial,"zero_adc":self.zero_adc,
            "servo_id":self.servo_id,"rf_kohm_assumed":158,
            "fsr_nominal_max_gf":1000,"two_kg_curve_point_is_not_rated":True,
            "force_values_are_unvalidated":True,
            "pc_timestamp":"PC arrival time in UTC, not hardware synchronized",
            "counts":{"pressure":len(self.pressure_rows),"ha8":len(self.ha8_rows),
                      "events":len(self.events),"paired":len(paired)}
        },ensure_ascii=False,indent=2),encoding="utf-8")
        self.exported=folder
        return folder


class StepMotionState:
    """No repeated motion before the last one-degree step reaches feedback target."""

    def __init__(self):
        self.target = None
        self.sent_at = None
        self.stable_count = 0

    @property
    def pending(self):
        return self.target is not None

    def begin(self,target,at):
        if self.pending:
            raise RuntimeError("上一个 1° 步进尚未完成")
        self.target=float(target)
        self.sent_at=float(at)
        self.stable_count=0

    def observe(self,angle,at,status):
        if not self.pending:
            return "idle"
        if int(status) != 0:
            return "fault"
        if float(at)-self.sent_at > 3.0:
            return "timeout"
        if abs(float(angle)-self.target) <= .2:
            self.stable_count+=1
        else:
            self.stable_count=0
        if self.stable_count>=2 and float(at)-self.sent_at>=.15:
            self.clear()
            return "complete"
        return "moving"

    def clear(self):
        self.target=None
        self.sent_at=None
        self.stable_count=0
