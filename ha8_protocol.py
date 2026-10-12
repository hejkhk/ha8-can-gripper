# -*- coding: utf-8 -*-
"""
HA8-U35H-M protocol layer
=========================

This file intentionally contains ONLY HA8 control/response protocol logic.

Verified end-to-end on the current hardware chain:
    Ping request : 12 4C 01 01 00 60
    Ping response: 05 1C 01 01 00 23

Other HA8 command layouts are preserved from the user's existing
HA8_CAN_Bridge_Debugger and HA8/Fashion Star protocol documentation.

Transport (USB-CAN/CTS100M) is NOT handled here.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Any

REQ_HEADER = b"\x12\x4C"
RESP_HEADER = b"\x05\x1C"

CMD_PING = 0x01
CMD_RESET_USER_DATA = 0x02
CMD_READ_DATA = 0x03
CMD_WRITE_DATA = 0x04
CMD_SET_ANGLE = 0x08
CMD_DAMPING = 0x09
CMD_QUERY_ANGLE = 0x0A
CMD_SET_ANGLE_BY_INTERVAL = 0x0B
CMD_SET_ANGLE_BY_VELOCITY = 0x0C
CMD_SET_MTURN_ANGLE = 0x0D
CMD_SET_MTURN_ANGLE_BY_INTERVAL = 0x0E
CMD_SET_MTURN_ANGLE_BY_VELOCITY = 0x0F
CMD_QUERY_MTURN_ANGLE = 0x10
CMD_RESET_MTURN = 0x11
CMD_BEGIN_ASYNC = 0x12
CMD_END_ASYNC = 0x13
CMD_MONITOR = 0x16
CMD_SET_ORIGIN = 0x17
CMD_STOP = 0x18
CMD_SYNC = 0x19

STOP_RELEASE = 0x10
STOP_HOLD = 0x11
STOP_DAMPING = 0x12

CMD_NAMES = {
    CMD_PING: "通讯检测",
    CMD_RESET_USER_DATA: "恢复用户数据",
    CMD_READ_DATA: "数据读取",
    CMD_WRITE_DATA: "自定义配置参数",
    CMD_SET_ANGLE: "简易单圈角度控制",
    CMD_DAMPING: "阻尼控制",
    CMD_QUERY_ANGLE: "单圈角度读取",
    CMD_SET_ANGLE_BY_INTERVAL: "高级单圈角度控制(时间)",
    CMD_SET_ANGLE_BY_VELOCITY: "高级单圈角度控制(速度)",
    CMD_SET_MTURN_ANGLE: "简易多圈角度控制",
    CMD_SET_MTURN_ANGLE_BY_INTERVAL: "高级多圈角度控制(时间)",
    CMD_SET_MTURN_ANGLE_BY_VELOCITY: "高级多圈角度控制(速度)",
    CMD_QUERY_MTURN_ANGLE: "多圈角度读取",
    CMD_RESET_MTURN: "重置圈数",
    CMD_BEGIN_ASYNC: "异步写入",
    CMD_END_ASYNC: "异步执行",
    CMD_MONITOR: "数据监控",
    CMD_SET_ORIGIN: "设置原点",
    CMD_STOP: "停止指令",
    CMD_SYNC: "同步指令",
}

STATUS_BITS = {
    0: "执行中",
    1: "指令错误",
    2: "堵转",
    3: "过压",
    4: "欠压",
    5: "电流错误",
    6: "功率错误",
    7: "温度错误",
}


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def hex_bytes(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def parse_hex_string(text: str) -> bytes:
    s = text.replace(",", " ").replace(";", " ").replace("\n", " ").replace("\t", " ")
    tokens = [t.strip() for t in s.split(" ") if t.strip()]
    out = bytearray()
    for token in tokens:
        if token.lower().startswith("0x"):
            token = token[2:]
        if not token:
            continue
        if len(token) > 2:
            if len(token) % 2:
                raise ValueError(f"HEX 长度必须为偶数：{token}")
            for i in range(0, len(token), 2):
                out.append(int(token[i:i + 2], 16))
        else:
            out.append(int(token, 16))
    return bytes(out)


def calc_checksum(prefix_without_checksum: bytes) -> int:
    return sum(prefix_without_checksum) & 0xFF


def build_request(cmd: int, content: bytes = b"") -> bytes:
    if not 0 <= cmd <= 0xFF:
        raise ValueError("CMD 必须在 0x00~0xFF")
    if len(content) > 255:
        raise ValueError("HA8 content 不能超过 255 字节")
    frame = REQ_HEADER + bytes((cmd, len(content))) + content
    return frame + bytes((calc_checksum(frame),))


def verify_response(frame: bytes) -> bool:
    if len(frame) < 5 or frame[:2] != RESP_HEADER:
        return False
    content_len = frame[3]
    return len(frame) == 5 + content_len and calc_checksum(frame[:-1]) == frame[-1]


def decode_status(status: int) -> str:
    if status == 0:
        return "正常 / 空闲"
    items = [name for bit, name in STATUS_BITS.items() if status & (1 << bit)]
    return "；".join(items) if items else f"未知状态 0x{status:02X}"


def temp_adc_to_celsius(adc: int) -> float | None:
    """10k NTC, B=3435, 12-bit ADC formula retained from the existing project."""
    try:
        adc = float(adc)
        if adc <= 0 or adc >= 4096:
            return None
        rr = adc / (4096.0 - adc)
        inv_t = math.log(rr) / 3435.0 + 1.0 / (273.15 + 25.0)
        return 1.0 / inv_t - 273.15
    except Exception:
        return None


class HA8Protocol:
    """Construct HA8 request packets. No serial/CAN code lives here."""

    @staticmethod
    def reset_user_data(servo_id: int) -> bytes:
        """Restore user configuration, including servo ID=0. Dangerous."""
        if not 0 <= servo_id <= 254:
            raise ValueError("Servo ID must be 0..254")
        return build_request(CMD_RESET_USER_DATA, struct.pack("<B", servo_id))

    @staticmethod
    def begin_async() -> bytes:
        """0x12: cache next angle command. Firmware V316+ compatibility required."""
        return build_request(CMD_BEGIN_ASYNC)

    @staticmethod
    def end_async(cancel: bool = False) -> bytes:
        """0x13: commit (cancel=0) or discard (cancel=1) cached motion."""
        return build_request(CMD_END_ASYNC, struct.pack("<B", int(bool(cancel))))

    @staticmethod
    def sync_raw(content: bytes) -> bytes:
        """0x19 raw payload. Caller must verify payload layout for installed firmware."""
        return build_request(CMD_SYNC, content)

    @staticmethod
    def sync_motion(
        targets: list[tuple[int, float]],
        multiturn: bool = False,
        mode: str = "velocity",
        interval_ms: int = 2000,
        velocity_dps: float = 120,
        t_acc_ms: int = 200,
        t_dec_ms: int = 200,
        power_mw: int = 5000,
    ) -> bytes:
        """Build 0x19 sync command per FashionStar MicroPython SDK.

        CONTENT = command_id:uint8, per_servo_block_len:uint8,
                  servo_count:uint8, concatenated servo blocks.
        Firmware V316+ required; actual HA8 compatibility must be tested.
        """
        if not targets or len(targets)>12:
            raise ValueError("同步目标需要 1~12 颗舵机")
        if len({sid for sid,_ in targets}) != len(targets):
            raise ValueError("同步目标舵机 ID 不得重复")
        power_mw=int(power_mw)
        if not 0<=power_mw<=65535:
            raise ValueError("功率范围 0~65535mW")
        interval_ms=int(interval_ms)
        t_acc_ms=int(t_acc_ms)
        t_dec_ms=int(t_dec_ms)
        velocity_raw=int(round(float(velocity_dps)*10))
        if not (0<=t_acc_ms<=65535 and 0<=t_dec_ms<=65535):
            raise ValueError("加减速时间必须为 0~65535ms")
        if mode=="velocity" and not (10<=velocity_raw<=7500):
            raise ValueError("速度范围 1~750 °/s")
        if mode not in ("simple","interval","velocity"):
            raise ValueError("模式仅支持 simple / interval / velocity")

        if multiturn:
            cmd={"simple":CMD_SET_MTURN_ANGLE,"interval":CMD_SET_MTURN_ANGLE_BY_INTERVAL,"velocity":CMD_SET_MTURN_ANGLE_BY_VELOCITY}[mode]
        else:
            cmd={"simple":CMD_SET_ANGLE,"interval":CMD_SET_ANGLE_BY_INTERVAL,"velocity":CMD_SET_ANGLE_BY_VELOCITY}[mode]

        parts=[]
        for sid,deg in targets:
            if not 0<=sid<=254:
                raise ValueError("舵机 ID 必须为 0..254")
            if not (-368640<=float(deg)<=368640 if multiturn else -180<=float(deg)<=180):
                raise ValueError("同步目标角度超出当前单圈/多圈范围")
            angle=int(round(float(deg)*10))
            if mode=="simple":
                if not 0<=interval_ms<=(0xFFFFFFFF if multiturn else 65535):
                    raise ValueError("运动时间超出协议可表示范围")
                fmt="<BiIH" if multiturn else "<BhHH"
                part=struct.pack(fmt,sid,angle,interval_ms,power_mw)
            elif mode=="interval":
                if interval_ms<t_acc_ms+t_dec_ms:
                    raise ValueError("总时长必须不少于加速时间+减速时间")
                if not 0<=interval_ms<=(0xFFFFFFFF if multiturn else 65535):
                    raise ValueError("运动时间超出范围")
                fmt="<BiIHHH" if multiturn else "<BhHHHH"
                part=struct.pack(fmt,sid,angle,interval_ms,t_acc_ms,t_dec_ms,power_mw)
            else:
                fmt="<BiHHHH" if multiturn else "<BhHHHH"
                part=struct.pack(fmt,sid,angle,velocity_raw,t_acc_ms,t_dec_ms,power_mw)
            parts.append(part)
        block_len=len(parts[0])
        payload=struct.pack("<BBB",cmd,block_len,len(parts))+b"".join(parts)
        return build_request(CMD_SYNC,payload)

    @staticmethod
    def sync_monitor(servo_ids: list[int]) -> bytes:
        """0x19 sync monitor payload from official MicroPython SDK."""
        if not servo_ids or len(servo_ids)>32:
            raise ValueError("同步监控 ID 个数 1..32")
        if len(set(servo_ids))!=len(servo_ids) or not all(0<=sid<=254 for sid in servo_ids):
            raise ValueError("同步监控 ID 需唯一且在 0..254")
        return build_request(CMD_SYNC,bytes((CMD_MONITOR,1,len(servo_ids)))+bytes(servo_ids))

    @staticmethod
    def ping(servo_id: int) -> bytes:
        return build_request(CMD_PING, struct.pack("<B", servo_id))

    @staticmethod
    def query_angle(servo_id: int, multiturn: bool = False) -> bytes:
        cmd = CMD_QUERY_MTURN_ANGLE if multiturn else CMD_QUERY_ANGLE
        return build_request(cmd, struct.pack("<B", servo_id))

    @staticmethod
    def monitor(servo_id: int) -> bytes:
        return build_request(CMD_MONITOR, struct.pack("<B", servo_id))

    @staticmethod
    def damping(servo_id: int, power_mw: int) -> bytes:
        power_mw = clamp(int(power_mw), 0, 65535)
        return build_request(CMD_DAMPING, struct.pack("<BH", servo_id, power_mw))

    @staticmethod
    def stop(servo_id: int, method: int, power_mw: int = 0) -> bytes:
        power_mw = clamp(int(power_mw), 0, 65535)
        return build_request(CMD_STOP, struct.pack("<BBH", servo_id, method, power_mw))

    @staticmethod
    def set_origin(servo_id: int) -> bytes:
        return build_request(CMD_SET_ORIGIN, struct.pack("<BB", servo_id, 0))

    @staticmethod
    def reset_multiturn(servo_id: int) -> bytes:
        return build_request(CMD_RESET_MTURN, struct.pack("<B", servo_id))

    @staticmethod
    def read_data(servo_id: int, address: int) -> bytes:
        return build_request(CMD_READ_DATA, struct.pack("<BB", servo_id, address))

    @staticmethod
    def write_data(servo_id: int, address: int, payload: bytes) -> bytes:
        return build_request(CMD_WRITE_DATA, struct.pack("<BB", servo_id, address) + payload)

    @staticmethod
    def move(
        servo_id: int,
        angle_deg: float,
        multiturn: bool,
        mode: str = "velocity",
        interval_ms: int = 2000,
        velocity_dps: float = 120.0,
        t_acc_ms: int = 200,
        t_dec_ms: int = 200,
        power_mw: int = 5000,
    ) -> bytes:
        """
        mode:
            simple   - simple time based command
            interval - trapezoidal profile by total time
            velocity - trapezoidal profile by target velocity
        """
        t_acc_ms = max(20, int(t_acc_ms))
        t_dec_ms = max(20, int(t_dec_ms))
        power_mw = clamp(int(power_mw), 0, 65535)

        if multiturn:
            angle_deg = clamp(float(angle_deg), -368640.0, 368640.0)
            angle_raw = int(round(angle_deg * 10.0))

            if mode == "simple":
                interval_ms = clamp(int(interval_ms), 0, 0xFFFFFFFF)
                content = struct.pack("<BiIH", servo_id, angle_raw, interval_ms, power_mw)
                return build_request(CMD_SET_MTURN_ANGLE, content)

            if mode == "interval":
                interval_ms = max(int(interval_ms), t_acc_ms + t_dec_ms)
                interval_ms = clamp(interval_ms, 0, 4096000)
                content = struct.pack(
                    "<BiIHHH",
                    servo_id, angle_raw, interval_ms, t_acc_ms, t_dec_ms, power_mw
                )
                return build_request(CMD_SET_MTURN_ANGLE_BY_INTERVAL, content)

            if mode == "velocity":
                velocity_dps = clamp(float(velocity_dps), 1.0, 750.0)
                velocity_raw = int(round(velocity_dps * 10.0))
                content = struct.pack(
                    "<BiHHHH",
                    servo_id, angle_raw, velocity_raw, t_acc_ms, t_dec_ms, power_mw
                )
                return build_request(CMD_SET_MTURN_ANGLE_BY_VELOCITY, content)

        else:
            angle_deg = clamp(float(angle_deg), -180.0, 180.0)
            angle_raw = int(round(angle_deg * 10.0))

            if mode == "simple":
                interval_ms = clamp(int(interval_ms), 0, 65535)
                content = struct.pack("<BhHH", servo_id, angle_raw, interval_ms, power_mw)
                return build_request(CMD_SET_ANGLE, content)

            if mode == "interval":
                interval_ms = max(int(interval_ms), t_acc_ms + t_dec_ms)
                interval_ms = clamp(interval_ms, 0, 65535)
                content = struct.pack(
                    "<BhHHHH",
                    servo_id, angle_raw, interval_ms, t_acc_ms, t_dec_ms, power_mw
                )
                return build_request(CMD_SET_ANGLE_BY_INTERVAL, content)

            if mode == "velocity":
                velocity_dps = clamp(float(velocity_dps), 1.0, 750.0)
                velocity_raw = int(round(velocity_dps * 10.0))
                content = struct.pack(
                    "<BhHHHH",
                    servo_id, angle_raw, velocity_raw, t_acc_ms, t_dec_ms, power_mw
                )
                return build_request(CMD_SET_ANGLE_BY_VELOCITY, content)

        raise ValueError(f"未知运动模式：{mode}")


class ResponseStreamParser:
    """Reassemble 05 1C HA8 responses across arbitrary CAN chunks."""

    def __init__(self):
        self.buf = bytearray()

    def reset(self):
        self.buf.clear()

    def feed(self, data: bytes) -> list[bytes]:
        self.buf.extend(data)
        packets: list[bytes] = []

        while True:
            if len(self.buf) < 2:
                break

            pos = self.buf.find(RESP_HEADER)
            if pos < 0:
                if self.buf and self.buf[-1] == RESP_HEADER[0]:
                    self.buf[:] = self.buf[-1:]
                else:
                    self.buf.clear()
                break

            if pos > 0:
                del self.buf[:pos]

            if len(self.buf) < 4:
                break

            total_len = 5 + self.buf[3]
            if len(self.buf) < total_len:
                break

            frame = bytes(self.buf[:total_len])
            if verify_response(frame):
                packets.append(frame)
                del self.buf[:total_len]
            else:
                del self.buf[0]

        return packets


@dataclass
class HA8Response:
    cmd: int
    cmd_name: str
    content: bytes
    raw: bytes
    servo_id: int | None = None
    fields: dict[str, Any] | None = None


def decode_response(frame: bytes) -> HA8Response:
    if not verify_response(frame):
        raise ValueError(f"非法 HA8 响应帧：{hex_bytes(frame)}")

    cmd = frame[2]
    content = frame[4:-1]
    fields: dict[str, Any] = {}
    sid = content[0] if content else None

    if cmd == CMD_PING and len(content) >= 1:
        fields["online"] = True

    elif cmd == CMD_QUERY_ANGLE and len(content) >= 3:
        sid, angle_raw = struct.unpack("<Bh", content[:3])
        fields["angle_deg"] = angle_raw / 10.0

    elif cmd == CMD_QUERY_MTURN_ANGLE and len(content) >= 7:
        sid, angle_raw, turn = struct.unpack("<Bih", content[:7])
        fields["angle_deg"] = angle_raw / 10.0
        fields["turn"] = turn

    elif cmd == CMD_MONITOR and len(content) >= struct.calcsize("<BHHHHBih"):        sid, voltage, current, power, temp_raw, status, angle_raw, turn = struct.unpack(
            "<BHHHHBih", content[:struct.calcsize("<BHHHHBih")]
        )
        fields.update({
            "voltage_mv": voltage,
            "current_ma": current,
            "power_mw": power,
            "temperature_adc": temp_raw,
            "temperature_c": temp_adc_to_celsius(temp_raw),
            "status": status,
            "status_text": decode_status(status),
            "angle_deg": angle_raw / 10.0,
            "turn": turn,
        })

    elif cmd == CMD_READ_DATA and len(content) >= 2:
        sid = content[0]
        fields["address"] = content[1]
        fields["data"] = content[2:]

    elif cmd == CMD_WRITE_DATA and len(content) >= 3:
        sid, address, result = struct.unpack("<BBB", content[:3])
        fields["address"] = address
        fields["write_ok"] = result == 1
        fields["result_raw"] = result

    else:
        fields["data"] = content[1:] if len(content) >= 1 else b""

    return HA8Response(
        cmd=cmd,
        cmd_name=CMD_NAMES.get(cmd, f"0x{cmd:02X}"),
        content=content,
        raw=frame,
        servo_id=sid,
        fields=fields,
    )