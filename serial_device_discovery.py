# -*- coding: utf-8 -*-
"""Identify F103 vs HA8 by validated wire protocols, not guessed COM numbers.

Discovery is an explicit operator action. Ports are opened only for bounded
read-only observation; silent ports receive *only* a HA8 Ping (no motor motion).
Unknown/busy/ambiguous ports are never silently assigned to a device.
"""
from __future__ import annotations
from dataclasses import dataclass
import time
import serial
from ha8_protocol import HA8Protocol, CMD_PING, ResponseStreamParser, decode_response
from pressure_validation import parse_frame


@dataclass(frozen=True)
class PortIdentity:
    port: str
    kind: str  # "ha8", "pressure", "unknown", "busy"
    servo_id: int | None = None
    reason: str = ""


def classify_f103_stream(raw: bytes) -> bool:
    """Require two consecutive valid, distinct F103 records (not one stray text)."""
    matches = []
    for line in raw.split(b"\n"):
        try:
            decoded = line.decode("ascii", errors="strict").strip()
        except UnicodeError:
            continue
        frame = parse_frame(decoded)
        if frame is not None and frame.status <= 7:
            matches.append(frame)
    return any(((b.sequence-a.sequence) & 0xFFFFFFFF) == 1
               and ((b.uptime_ms-a.uptime_ms) & 0xFFFFFFFF) < 1000
               for a,b in zip(matches,matches[1:]))


def classify_ha8_reply(raw: bytes, servo_id: int) -> bool:
    """Validate sync, length, checksum, command and requested servo ID."""
    parser = ResponseStreamParser()
    for frame in parser.feed(raw):
        rsp = decode_response(frame)
        if (rsp.cmd == CMD_PING and rsp.servo_id == servo_id
                and rsp.fields.get("online") and len(rsp.content) == 1):
            return True
    return False


def probe_port(port: str, servo_ids=(0,), serial_factory=None,
               passive_seconds: float = 0.55, ping_seconds: float = 0.35,
               now=None) -> PortIdentity:
    factory = serial_factory or serial.Serial
    clock = now or time.monotonic
    try:
        # No DTR/RTS toggling beyond the USB-UART driver's ordinary open defaults.
        with factory(port=port, baudrate=115200, bytesize=8, parity=serial.PARITY_NONE,
                     stopbits=1, timeout=0.07, write_timeout=0.3) as conn:
            stream = bytearray()
            cutoff = clock()+passive_seconds
            while clock() < cutoff:
                chunk = conn.read(128)
                if chunk:
                    stream.extend(chunk)
                    if len(stream) > 5000:
                        stream = stream[-5000:]
                    if classify_f103_stream(stream):
                        return PortIdentity(port,"pressure",reason="F103 连续上报有效 P 帧")
            # Do not probe an already talking device with an unrelated HA8 command.
            if stream:
                return PortIdentity(port,"unknown",reason="端口有数据，但不是有效 F103 流")
            checked = set()
            for sid in servo_ids:
                if not isinstance(sid,int) or not 0 <= sid <= 254 or sid in checked:
                    continue
                checked.add(sid)
                conn.write(HA8Protocol.ping(sid))
                conn.flush()
                reply = bytearray()
                deadline = clock()+ping_seconds
                while clock()<deadline:
                    block = conn.read(128)
                    if block:
                        reply.extend(block)
                        if len(reply)>512:
                            reply = reply[-512:]
                        if classify_ha8_reply(reply,sid):
                            return PortIdentity(port,"ha8",sid,"校验通过的 HA8 Ping 回包")
                # A device responded with a non-HA8 payload: never try more IDs.
                if reply:
                    break
            return PortIdentity(port,"unknown",reason="无有效 F103/HA8 协议响应")
    except (serial.SerialException,OSError,ValueError) as exc:
        return PortIdentity(port,"busy",reason=f"端口无法探测：{exc}")


def discover_ports(port_names, servo_ids=(0,), serial_factory=None):
    """Bounded scan; caller decides whether/which unique devices to connect."""
    names = list(dict.fromkeys(str(p) for p in port_names if str(p).strip()))
    if len(names)>16:
        raise ValueError("串口数量过多，请手动选择要扫描的设备")
    return [probe_port(p,servo_ids=servo_ids,serial_factory=serial_factory) for p in names]


def unique_selection(identities):
    found = {}
    for kind in ("ha8","pressure"):
        hits = [p for p in identities if p.kind==kind]
        found[kind] = hits[0] if len(hits)==1 else None
    return found
