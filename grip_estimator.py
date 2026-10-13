# -*- coding: utf-8 -*-
"""Non-safety-rated HA8 torque reference and tentative grip detection.

A vendor dynamic characteristic curve is NOT equivalent to a calibrated
static shaft torque measurement; a worm drive can support load while drawing
little current. This module never declares a verified grip or commands motors.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from statistics import median


# Approximate reference points read visually from the published 12 V dynamic
# characteristic figure, NOT original digitized calibration data. Units A,Nm.
# User may replace with their own measured pairs.
REFERENCE_DYNAMIC_POINTS = (
    (0.30, 0.30),
    (0.40, 0.50),
    (0.50, 0.75),
    (0.60, 1.00),
    (0.70, 1.20),
)


def parse_curve(text: str) -> tuple[tuple[float, float], ...]:
    """Parse '0.30:0.30, 0.40:0.50' into strictly increasing points."""
    pairs = []
    for element in text.replace(';', ',').split(','):
        element = element.strip()
        if not element:
            continue
        parts = element.split(':')
        if len(parts) != 2:
            raise ValueError('曲线格式应为 电流A:扭矩Nm,电流A:扭矩Nm')
        x, y = float(parts[0]), float(parts[1])
        if not isfinite(x) or not isfinite(y) or x < 0 or y < 0:
            raise ValueError('曲线参数必须是非负有限数字')
        if pairs and x <= pairs[-1][0]:
            raise ValueError('电流必须严格递增，且不能重复')
        pairs.append((x, y))
    if len(pairs) < 2:
        raise ValueError('至少需要两个曲线点')
    return tuple(pairs)


def format_curve(points: tuple[tuple[float, float], ...]) -> str:
    return ', '.join(f'{x:.2f}:{y:.2f}' for x, y in points)


def dynamic_torque_reference(
    current_a: float, speed_dps: float,
    points: tuple[tuple[float, float], ...] = REFERENCE_DYNAMIC_POINTS,
    minimum_speed_dps: float = 2.0,
) -> float | None:
    """Return bounded interpolation ONLY under motion, else None.

    No extrapolation beyond known current points; does not represent holding
    torque, finger force, or a safety-certified load limit.
    """
    if not isfinite(current_a) or not isfinite(speed_dps):
        return None
    if abs(speed_dps) < minimum_speed_dps or current_a < points[0][0] or current_a > points[-1][0]:
        return None
    for (x0, y0), (x1, y1) in zip(points[:-1], points[1:]):
        if x0 <= current_a <= x1:
            return y0 + (current_a - x0) * (y1 - y0) / (x1 - x0)
    return None


class GripState(str, Enum):
    IDLE = '未开始'
    CLOSING = '闭合观察中'
    CONTACT = '疑似接触'
    CANDIDATE = '疑似夹持稳定（未校验）'
    UNVERIFIED = '稳定候选；未设置有效夹持角度区间'
    NO_OBJECT = '未见明显接触'
    FAULT = '异常／疑似卡死'
    STALE = '监控反馈超时'
    INVALID = '采样无效'


@dataclass(frozen=True)
class GripSettings:
    baseline_a: float = 0.20
    contact_delta_a: float = 0.18
    minimum_grip_current_a: float = 0.55
    maximum_safe_current_a: float = 1.50
    low_speed_dps: float = 2.0
    stable_seconds: float = 0.50
    minimum_travel_deg: float = 2.0
    closing_direction: int = 1  # +1 angle increases while closing, -1 decreases
    valid_angle_min: float | None = None
    valid_angle_max: float | None = None
    stale_seconds: float = 1.50
    window_size: int = 5

    def validate(self) -> None:
        v = (
            self.baseline_a, self.contact_delta_a, self.minimum_grip_current_a,
            self.maximum_safe_current_a, self.low_speed_dps,
            self.stable_seconds, self.minimum_travel_deg, self.stale_seconds,
        )
        if not all(isfinite(x) for x in v):
            raise ValueError('阈值必须为有限数字')
        if self.baseline_a < 0 or self.contact_delta_a <= 0 or self.minimum_grip_current_a <= 0:
            raise ValueError('基线必须≥0，电流阈值必须>0')
        if self.maximum_safe_current_a <= max(self.baseline_a, self.minimum_grip_current_a):
            raise ValueError('异常电流阈值必须高于空载基线和夹持电流阈值')
        if self.low_speed_dps <= 0 or self.stable_seconds < 0.2 or self.minimum_travel_deg <= 0:
            raise ValueError('角速度阈值、稳定时间和最小运动角度不合理')
        if self.stale_seconds <= 0.1 or self.window_size < 3:
            raise ValueError('反馈超时和滤波窗口不合理')
        if self.closing_direction not in (-1, 1):
            raise ValueError('闭合方向只能为 +1 或 -1')
        if (self.valid_angle_min is None) != (self.valid_angle_max is None):
            raise ValueError('有效角度区间上下限需同时填写或同时留空')
        if self.valid_angle_min is not None and not self.valid_angle_min < self.valid_angle_max:
            raise ValueError('有效角度区间下限必须小于上限')


@dataclass(frozen=True)
class GripSample:
    timestamp: float  # monotonic/real seconds: must increase within one session
    angle_deg: float
    current_a: float
    status_bits: int = 0


@dataclass(frozen=True)
class GripResult:
    state: GripState
    current_filtered_a: float | None
    angle_speed_dps: float | None
    dynamic_torque_nm: float | None
    travel_deg: float
    note: str


class GripDetector:
    """Pure data-state estimator; call arm() before each gripping attempt."""

    def __init__(self, settings: GripSettings | None = None, curve=REFERENCE_DYNAMIC_POINTS):
        self.settings = settings or GripSettings()
        self.settings.validate()
        self.curve = curve
        self.reset()

    def reset(self) -> None:
        self.armed = False
        self.state = GripState.IDLE
        self.samples: deque[GripSample] = deque(maxlen=max(3, self.settings.window_size))
        self.start_angle: float | None = None
        self.last_timestamp: float | None = None
        self._contact_start: float | None = None
        self._candidate_start: float | None = None
        self._had_contact = False
        self._fault_latched = False
        self._max_progress = 0.0
        self.last_result = GripResult(GripState.IDLE, None, None, None, 0, '仅作实验参考，不作为自动抬升依据')

    def arm(self) -> None:
        self.reset()
        self.armed = True
        self.state = GripState.CLOSING
        self.last_result = GripResult(self.state, None, None, None, 0, '请开始闭合；同时开启周期监控')

    def check_stale(self, now: float) -> GripResult:
        if self.armed and self.last_timestamp is not None and now - self.last_timestamp > self.settings.stale_seconds:
            self.state = GripState.STALE
            self.last_result = GripResult(self.state, None, None, None,
                                          self._max_progress, '监控数据超过设定时限，请勿按夹稳处理')
        return self.last_result

    def observe(self, sample: GripSample) -> GripResult:
        if (not all(isfinite(x) for x in (sample.timestamp, sample.angle_deg, sample.current_a))
            or sample.current_a < 0 or not 0 <= sample.status_bits <= 255):
            self.state = GripState.INVALID
            self.last_result = GripResult(self.state, None, None, None,
                                          self._max_progress, '监控回包数据不合法')
            return self.last_result
        if self.last_timestamp is not None and sample.timestamp <= self.last_timestamp:
            return self.last_result  # discard out-of-order data
        if self.last_timestamp is not None and sample.timestamp - self.last_timestamp > self.settings.stale_seconds:
            self.samples.clear()
            self._candidate_start = None
            self._contact_start = None
            self.state = GripState.STALE if self.armed else GripState.IDLE
        self.last_timestamp = sample.timestamp
        self.samples.append(sample)
        filtered_current = median(s.current_a for s in self.samples)
        if len(self.samples) > 1 and self.samples[-1].timestamp > self.samples[0].timestamp:
            dt = self.samples[-1].timestamp - self.samples[0].timestamp
            speed = (self.samples[-1].angle_deg - self.samples[0].angle_deg) / dt
        else:
            speed = None
        torque = dynamic_torque_reference(filtered_current, speed or 0.0, self.curve)
        if not self.armed:
            self.state = GripState.IDLE
            self.last_result = GripResult(self.state, filtered_current, speed, torque, 0, '点击“开始一次夹持检测”才会进行接触判定')
            return self.last_result
        if self.start_angle is None:
            self.start_angle = sample.angle_deg
        progress = (sample.angle_deg - self.start_angle) * self.settings.closing_direction
        self._max_progress = max(self._max_progress, progress)
        # Bit 2 stall + bit 3..7 protection. Bit 0 indicates working, not fault.
        fault = bool(sample.status_bits & 0xFC) or filtered_current > self.settings.maximum_safe_current_a
        if fault:
            self._fault_latched = True
        if self._fault_latched:
            self.state = GripState.FAULT
            self._candidate_start = None
            self.last_result = GripResult(self.state, filtered_current, speed, torque,
                                          self._max_progress, '曾发生堵转/保护位或过流；故障已锁存，重置前不得判定为夹稳')
            return self.last_result
        # Prevent idle, wrong closing direction, or limit against mechanical stop
        # from immediately becoming a 'grip' result.
        if self._max_progress < self.settings.minimum_travel_deg:
            self.state = GripState.CLOSING
            self._candidate_start = None
            self.last_result = GripResult(self.state, filtered_current, speed, torque,
                                          self._max_progress, '尚未满足最小闭合角度')
            return self.last_result
        low_speed = speed is not None and abs(speed) <= self.settings.low_speed_dps
        elevated = filtered_current >= self.settings.baseline_a + self.settings.contact_delta_a
        contact_now = low_speed and elevated
        if contact_now:
            if self._contact_start is None:
                self._contact_start = sample.timestamp
            if sample.timestamp - self._contact_start >= 0.2:
                self._had_contact = True
        else:
            self._contact_start = None
            self._candidate_start = None
        if not self._had_contact:
            self.state = GripState.CLOSING
            self.last_result = GripResult(self.state, filtered_current, speed, torque,
                                          self._max_progress, '等待电流抬升且转速下降')
            return self.last_result
        self.state = GripState.CONTACT
        note = '电流上升且闭合变慢，疑似接触'
        if contact_now and filtered_current >= self.settings.minimum_grip_current_a:
            if self._candidate_start is None:
                self._candidate_start = sample.timestamp
            if sample.timestamp - self._candidate_start >= self.settings.stable_seconds:
                if self.settings.valid_angle_min is None:
                    self.state = GripState.UNVERIFIED
                    note = '疑似保持稳定，但未设有效夹持角区间，可能顶到机械限位'
                elif self.settings.valid_angle_min <= sample.angle_deg <= self.settings.valid_angle_max:
                    self.state = GripState.CANDIDATE
                    note = '多条件稳定候选；仍不能证明无打滑或可安全抬升'
                else:
                    self.state = GripState.FAULT
                    note = '接触角度不在允许区间，可能顶到机械限位'
        else:
            self._candidate_start = None
        self.last_result = GripResult(self.state, filtered_current, speed, torque,
                                      self._max_progress, note)
        return self.last_result