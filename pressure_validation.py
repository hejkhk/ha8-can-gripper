# -*- coding: utf-8 -*-
"""Read-only F103 pressure integration: validation/experiments, NEVER servo control.

Reuse the independently maintained IMS003/AO mathematical model instead of
copying its manufacturer lookup table. This module must not send HA8 frames.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from statistics import median
import csv
import math
import threading
import time
import serial
from pressure_protocol import parse_frame, estimate_circuit_force_g


class PressureSerialLink:
    """One independent read-only USB-TTL COM port. Callback is on worker thread."""

    def __init__(self, on_frame, on_error):
        self.on_frame = on_frame
        self.on_error = on_error
        self.conn = None
        self._stop = threading.Event()
        self._worker = None

    @property
    def is_open(self):
        return self.conn is not None and bool(self.conn.is_open)

    def open(self, port: str):
        if not port:
            raise ValueError("请先选择压力模块 USB-TTL 的 COM 口")
        self.close()
        conn = serial.Serial(port, 115200, timeout=0.15)
        self.conn = conn
        self._stop = threading.Event()  # New event per session: no cross-port reader race.
        self._worker = threading.Thread(target=self._read, args=(conn, self._stop),
                                        name="fsr-rx", daemon=True)
        self._worker.start()

    def _read(self, conn, stopped):
        try:
            while not stopped.is_set():
                raw = conn.readline()
                if not raw or len(raw) > 96:
                    continue
                try:
                    line = raw.decode("ascii", errors="strict")
                except UnicodeError:
                    continue
                frame = parse_frame(line)
                if frame is not None:
                    self.on_frame(frame, time.monotonic())
        except (OSError, serial.SerialException) as exc:
            if not stopped.is_set():
                self.on_error(exc)

    def close(self):
        self._stop.set()
        conn, self.conn = self.conn, None
        if conn is not None:
            try:
                conn.close()
            except (OSError, serial.SerialException):
                pass
        worker, self._worker = self._worker, None
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=0.35)


@dataclass(frozen=True)
class PressurePoint:
    at: float
    sequence: int
    adc: int
    mv: int
    flags: int


class PressureEvidence:
    """Zero-reference contact *evidence*, not calibrated grip or slip verification."""

    def __init__(self, rf_kohm=158.0):
        self.rf_kohm = rf_kohm
        self.zero_adc = None
        self.zero_noise_adc = None
        self.samples = deque(maxlen=2000)
        self.last_received_at = None
        self.last_bad_at = None

    def add(self, frame, at):
        self.last_received_at = at
        if frame.status == 0 and 0 <= frame.adc < 4085:
            self.samples.append(PressurePoint(at, frame.sequence, frame.adc, frame.voltage_mv,
                                               frame.status))
        else:
            self.last_bad_at = at

    def latest(self, now=None):
        now = time.monotonic() if now is None else now
        if self.samples and now - self.samples[-1].at <= 0.3:
            if self.last_bad_at is None or self.samples[-1].at > self.last_bad_at:
                return self.samples[-1]
        return None

    def capture_zero(self, now=None):
        now = time.monotonic() if now is None else now
        points = [s for s in self.samples if now - 1.5 <= s.at <= now]
        if (len(points) < 30 or points[-1].at - points[0].at < 0.7
                or self.latest(now) is None):
            raise ValueError("先让压力片完全无载、连续稳定采集至少 1 秒")
        data = [x.adc for x in points]
        base = median(data)
        mad = median(abs(x-base) for x in data)
        if max(data)-min(data) > 100 or mad > 15:
            raise ValueError("无载读数波动过大，检查接线/压力后重新采零点")
        self.zero_adc = float(base)
        self.zero_noise_adc = max(1.0, 1.4826 * mad)
        return self.zero_adc

    def ready_for_trial(self, now=None):
        """Check that a fresh, valid, unloaded zero is ready for a NEW trial.

        This does not prove there is no physical load: the operator must make
        sure the sensor is free before capturing the zero.
        """
        now = time.monotonic() if now is None else now
        if self.zero_adc is None or self.zero_noise_adc is None:
            return False, "请先在压力片完全无载时采集零点"
        if self.latest(now) is None:
            return False, "压力数据失效/超时，请确认连接与状态后重新归零"
        recent = [p.adc for p in self.samples if 0 <= now - p.at <= 0.30]
        if len(recent) < 8:
            return False, "无载数据不足，请静置片刻再开始标定"
        offset = median(recent) - self.zero_adc
        threshold = max(15.0, 5.0 * self.zero_noise_adc)
        if abs(offset) > threshold:
            return False, "压力片当前不在零点附近：请松开夹爪，待读数恢复后再开始"
        return True, "无载零点及实时数据有效"

    def theoretical_force_g(self, adc):
        if self.zero_adc is None:
            return None
        # 158 kOhm is configured, not independently measured in-circuit.
        value = estimate_circuit_force_g(adc, self.rf_kohm, self.zero_adc)
        # The factory nominal rating is 1 kg; never plot the 2 kg reference as valid.
        return value if value is not None and 0 <= value <= 1000 else None

    def sustained(self, now=None, seconds=0.9):
        """Optional persistence evidence; not proof of mechanical grip or zero slip."""
        now = time.monotonic() if now is None else now
        if self.zero_adc is None or self.latest(now) is None:
            return False
        points = [x for x in self.samples if 0 <= now-x.at <= seconds]
        if len(points) < 20 or points[-1].at - points[0].at < 0.7:
            return False
        threshold = max(20.0, 6.0*self.zero_noise_adc)
        passed = sum(x.adc-self.zero_adc >= threshold for x in points)
        return passed >= math.ceil(0.85*len(points))

    def evidence(self, now=None):
        """Return (label, measured_delta_adc). No path returns 'grip proven'."""
        now = time.monotonic() if now is None else now
        if self.zero_adc is None:
            return "未校零，无法判断压力接触", None
        if self.latest(now) is None:
            return "压力数据不足或已过期", None
        points = [s for s in self.samples if 0 <= now-s.at <= 0.6]
        if len(points) < 8 or now-points[-1].at > 0.3:
            return "压力数据不足或已过期", None
        recent = points[-min(25, len(points)):]
        delta = median(x.adc for x in recent)-self.zero_adc
        threshold = max(20.0, 6.0*self.zero_noise_adc)
        if delta >= threshold:
            if self.sustained(now):
                return "持续受压证据（仍未验证是否打滑）", delta
            return "检测到压力接触证据（不代表可靠抓稳）", delta
        return "未检测到足够的压力接触证据", delta


@dataclass(frozen=True)
class MatchedPoint:
    pc_time_s: float
    trial: str
    servo_id: int
    current_a: float
    angle_deg: float
    phase: str
    status: int
    pressure_adc: int
    pressure_delta_adc: float
    pressure_mv: int
    theoretical_gf: float | None
    pressure_seq: int
    skew_ms: float


class CurveRecorder:
    """Correlate fresh measurements on PC arrival time. No clock synchronization."""

    HEADERS = ["pc_time_s","trial","servo_id","current_A","angle_deg",
               "phase","ha8_status","pressure_ADC","pressure_delta_ADC",
               "pressure_mV","theoretical_gf_unverified","pressure_seq","skew_ms"]

    def __init__(self):
        self.active = False
        self.trial = ""
        self.rows = []

    def start(self, trial=""):
        self.rows = []
        self.trial = (trial or "实验").strip()[:48]
        self.active = True

    def stop(self):
        self.active = False

    def add(self, at, sid, fields, pressure: PressureEvidence, phase):
        if not self.active or len(self.rows) >= 30000:
            if len(self.rows) >= 30000:
                self.active = False
            return False
        point = pressure.latest(at)
        if point is None or pressure.zero_adc is None:
            return False
        skew = 1000.0*(at-point.at)
        if skew < 0 or skew > 180:
            return False
        status = int(fields["status"])
        if status & 0xFE:
            return False
        amps = float(fields["current_ma"])/1000.0
        angle = float(fields["angle_deg"])
        if not math.isfinite(amps) or not math.isfinite(angle):
            return False
        delta = point.adc-pressure.zero_adc
        gf = pressure.theoretical_force_g(point.adc)
        self.rows.append(MatchedPoint(time.time(), self.trial, int(sid), amps, angle,
                                      phase or "idle", status, point.adc, delta,
                                      point.mv, gf, point.sequence, skew))
        return True

    def curve(self, unit="adc", bins=12):
        """Median-binned *reference* relationship; not a calibrated force curve."""
        pairs = []
        for r in self.rows:
            y = r.pressure_delta_adc if unit == "adc" else r.theoretical_gf
            if y is not None and math.isfinite(y) and math.isfinite(r.current_a):
                pairs.append((r.current_a, y))
        if len(pairs) < 8:
            return pairs, []
        lo, hi = min(x for x,y in pairs), max(x for x,y in pairs)
        if hi-lo < 0.03:
            return pairs, []
        bins = max(3, min(int(bins), max(3, len(pairs)//4)))
        groups = [[] for _ in range(bins)]
        for x,y in pairs:
            i = min(bins-1, int((x-lo)/(hi-lo)*bins))
            groups[i].append((x,y))
        return pairs, [(median(x for x,y in group), median(y for x,y in group))
                       for group in groups if len(group) >= 2]

    def export_csv(self, path):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(self.HEADERS)
            for r in self.rows:
                writer.writerow((r.pc_time_s,r.trial,r.servo_id,r.current_a,r.angle_deg,
                                 r.phase,r.status,r.pressure_adc,r.pressure_delta_adc,
                                 r.pressure_mv, "" if r.theoretical_gf is None else r.theoretical_gf,
                                 r.pressure_seq,round(r.skew_ms,2)))
