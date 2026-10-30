"""STM32 夹爪压力协议和测力估算函数（不依赖 GUI，可单独测试）。"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import Optional
import math


@dataclass(frozen=True)
class PressureFrame:
    sequence: int
    uptime_ms: int
    adc: int
    voltage_mv: int
    status: int


def parse_frame(line: str) -> Optional[PressureFrame]:
    """协议 P,序号,毫秒,12位ADC,毫伏,状态。"""
    parts = line.strip().split(",")
    if len(parts) != 6 or parts[0] != "P":
        return None
    try:
        seq, uptime, adc, mv, status = (int(x) for x in parts[1:])
    except ValueError:
        return None
    if not (0 <= seq <= 4294967295 and 0 <= uptime <= 4294967295
            and 0 <= adc <= 4095 and 0 <= mv <= 3300 and 0 <= status <= 255):
        return None
    return PressureFrame(seq, uptime, adc, mv, status)


def validate_points(points: list[dict]) -> bool:
    """多点实测标定：力值、ADC 必须严格单调（支持信号反向）。"""
    if len(points) < 2:
        return False
    try:
        by_force = sorted((float(p["g"]), float(p["adc"])) for p in points)
    except (KeyError, ValueError, TypeError):
        return False
    if any(not (math.isfinite(g) and math.isfinite(adc) and 0 <= g <= 2000 and 0 <= adc <= 4095)
           for g, adc in by_force):
        return False
    if any(by_force[i + 1][0] <= by_force[i][0] for i in range(len(by_force) - 1)):
        return False
    slopes = [by_force[i + 1][1] - by_force[i][1] for i in range(len(by_force) - 1)]
    return all(x > 0 for x in slopes) or all(x < 0 for x in slopes)


def _interpolate(x: float, xy: list[tuple[float, float]]) -> float:
    """在严格递增的节点 x 轴上，执行线性插值。调用者负责范围验证。"""
    xs = [p[0] for p in xy]
    index = bisect_left(xs, x)
    if index == 0:
        return xy[0][1]
    if index == len(xs):
        return xy[-1][1]
    x0, y0 = xy[index - 1]
    x1, y1 = xy[index]
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0)


def estimate_force_g(adc: float, points: list[dict]) -> Optional[float]:
    """实测多点标定的分段插值；禁止向高力值端外推。"""
    if not validate_points(points) or not math.isfinite(adc):
        return None
    by_adc = sorted((float(p["adc"]), float(p["g"])) for p in points)
    xs = [p[0] for p in by_adc]
    if adc < xs[0]:
        return 0.0 if by_adc[0][1] == 0.0 else None
    if adc > xs[-1]:
        return 0.0 if by_adc[-1][1] == 0.0 else None
    return _interpolate(adc, by_adc)


# 用户上传的 IMS003-C10A-1KG V1.0，第 2 页表格。
# 单位：力 gf（克力），电导 1/kΩ（即 mS）；2 kg 是厂家参考点，超出首页标称 1kg 量程。
MANUFACTURER_POINTS = (
    (0.0, 0.0),
    (50.0, 0.0063),
    (100.0, 0.0111),
    (200.0, 0.0204),
    (500.0, 0.0556),
    (1000.0, 0.1020),
    (2000.0, 0.2000),
)


def manufacturer_conductance(force_g: float) -> Optional[float]:
    """根据厂家表格插值得到电导（1/kΩ），不外推。"""
    if not math.isfinite(force_g) or not 0 <= force_g <= 2000:
        return None
    return _interpolate(force_g, list(MANUFACTURER_POINTS))


def factory_reference_ready(zero_adc: Optional[float], ref_adc: Optional[float],
                            ref_g: Optional[float]) -> bool:
    """参考曲线法要求无载零点和一个 *已知载荷* 点来确定电导→ADC 的增益。"""
    try:
        z, a, g = float(zero_adc), float(ref_adc), float(ref_g)
    except (TypeError, ValueError):
        return False
    return (all(map(math.isfinite, (z, a, g))) and 0 <= z <= 4095 and 0 <= a <= 4095
            and 50 <= g <= 2000 and abs(a - z) >= 20)


def estimate_factory_force_g(adc: float, zero_adc: Optional[float],
                             ref_adc: Optional[float], ref_g: Optional[float]) -> Optional[float]:
    """利用厂家 *电导-力* 数据 + 实测 AO 的零点/参考点估算夹爪受力。

    假设在未饱和范围内 AO 与传感器电导近似仿射：ADC = b + k * G。
    转换模块具体电路/增益未知，因此不是免标定的绝对测力。
    """
    if not factory_reference_ready(zero_adc, ref_adc, ref_g) or not math.isfinite(adc):
        return None
    z, a, g = float(zero_adc), float(ref_adc), float(ref_g)
    reference_conductance = manufacturer_conductance(g)
    # 对应 ADC 相对零点方向的变化；允许模块输出随受力下降。
    conductance = (adc - z) / (a - z) * reference_conductance
    if conductance <= 0:
        return 0.0
    full_scale_conductance = MANUFACTURER_POINTS[-1][1]
    if conductance > full_scale_conductance:
        return None
    return _interpolate(conductance, [(c, f) for f, c in MANUFACTURER_POINTS])
