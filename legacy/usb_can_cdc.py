# -*- coding: utf-8 -*-
"""
Direct USB-CAN CDC transport for the user's CAN_LIN_TOOL_V6.0 adapter.

Reverse-engineered and verified on the user's adapter:
- USB CDC virtual COM, 115200 8N1
- CAN bus configured by replaying the captured initialization sequence
- current validated CAN setting: Classical CAN, 1 Mbps, standard data frame
- 20-byte CAN record:

    [0]      0x01
    [1:5]    CAN ID, uint32 little-endian
    [5:11]   flags/reserved (0 for validated standard data frames)
    [11]     DLC
    [12:20]  DATA[8], zero padded

Verified TX:
  ID 0x6A0 / 12 4C 01 01 00 60
Verified RX:
  ID 0x6A1 / 05 1C 01 01 00 23
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
import threading
import time

import serial


CAN_BITRATE_TEXT = "1 Mbps"
CDC_BAUD = 115200
DEFAULT_TX_ID = 0x6A0
DEFAULT_RX_ID = 0x6A1

# Exact startup sequence captured from the original CAN_LIN_TOOL_V6.0
# and subsequently proven by the successful HA8 Ping round-trip.
INIT_COMMANDS = [
    bytes.fromhex("03 03 00"),
    bytes.fromhex("06 01"),
    bytes.fromhex("03 01 E8 03 00 00 09 00 00 05 00"),
    bytes.fromhex("03 02 04 00"),
    bytes.fromhex("03 04 14 00 00 00 D0 07 00 00"),

    bytes.fromhex("03 02 00 00 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 01 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 02 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 03 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 04 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 05 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 06 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 07 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 08 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 09 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 0A 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 0B 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 0C 00 00 00 00 00 00 00 00 00 00 00"),
    bytes.fromhex("03 02 00 0D 00 00 00 00 00 00 00 00 00 00 00"),

    bytes.fromhex("03 02 06"),
    bytes.fromhex("04 01 00 4B 00 00"),
    bytes.fromhex("04 03 03 00"),
    bytes.fromhex("04 02 03 03 00 00"),
    bytes.fromhex("04 03 01 00"),
    bytes.fromhex("06 04"),
    bytes.fromhex("04 03 03 03 01 00 00 00 01 00 00 00"),
    bytes.fromhex("04 03 03 04 0A 00 00 00"),
]


def hex_bytes(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


@dataclass(frozen=True)
class CanFrame:
    can_id: int
    data: bytes
    is_extended: bool = False
    is_remote: bool = False

    @property
    def dlc(self) -> int:
        return len(self.data)


def build_standard_data_record(can_id: int, data: bytes) -> bytes:
    if not 0 <= can_id <= 0x7FF:
        raise ValueError("V1 仅支持已验证的 11 位标准 CAN ID (0x000~0x7FF)")
    if len(data) > 8:
        raise ValueError("Classical CAN 单帧最大 8 字节")

    record = bytearray(20)
    record[0] = 0x01
    record[1:5] = struct.pack("<I", can_id)
    # bytes 5~10 are zero for the validated standard data frame mode
    record[11] = len(data)
    record[12:12 + len(data)] = data
    return bytes(record)


def parse_standard_data_record(record: bytes) -> CanFrame:
    if len(record) != 20:
        raise ValueError("USB-CAN record 必须为 20 字节")
    if record[0] != 0x01:
        raise ValueError(f"未知 record 类型 0x{record[0]:02X}")

    dlc = record[11]
    if dlc > 8:
        raise ValueError(f"非法 CAN DLC={dlc}")

    can_id = struct.unpack("<I", record[1:5])[0]
    if can_id > 0x7FF:
        raise ValueError(f"V1 收到非标准 ID/未知标志：0x{can_id:X}")

    return CanFrame(can_id=can_id, data=bytes(record[12:12 + dlc]))


class UsbCanCdc:
    """
    Direct COM-port driver for the verified USB-CAN adapter.

    on_frame(frame: CanFrame) is called from the reader thread.
    on_error(exc) is called from the reader thread.
    on_raw(direction: str, bytes_data: bytes) is optional diagnostics.
    """

    def __init__(self, on_frame=None, on_error=None, on_raw=None):
        self.ser: serial.Serial | None = None
        self.on_frame = on_frame or (lambda frame: None)
        self.on_error = on_error or (lambda exc: None)
        self.on_raw = on_raw or (lambda direction, data: None)

        self._running = False
        self._reader_thread: threading.Thread | None = None
        self._tx_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._last_ha8_tx = 0.0
        self.min_ha8_command_gap_s = 0.008
        self._rxbuf = bytearray()

    @property
    def is_open(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def open(self, port: str):
        self.close()

        ser = serial.Serial(
            port=port,
            baudrate=CDC_BAUD,
            bytesize=8,
            parity=serial.PARITY_NONE,
            stopbits=1,
            timeout=0.02,
            write_timeout=1.0,
        )
        self.ser = ser

        # Let Windows/CDC settle and remove stale bytes.
        time.sleep(0.20)
        self._drain(0.10)

        # Replay the exact proven initialization sequence.
        for cmd in INIT_COMMANDS:
            ser.write(cmd)
            ser.flush()
            self.on_raw("INIT_TX", cmd)
            time.sleep(0.002)

        time.sleep(0.10)
        self._drain(0.10)

        self._rxbuf.clear()
        self._running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def close(self):
        self._running = False
        ser = self.ser
        self.ser = None

        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass

        th = self._reader_thread
        self._reader_thread = None
        if th is not None and th.is_alive() and th is not threading.current_thread():
            th.join(timeout=0.2)

        self._rxbuf.clear()

    def _drain(self, duration: float):
        ser = self.ser
        if ser is None:
            return b""

        out = bytearray()
        end = time.monotonic() + duration
        while time.monotonic() < end:
            try:
                n = ser.in_waiting
                if n:
                    out.extend(ser.read(n))
                else:
                    time.sleep(0.005)
            except Exception:
                break
        return bytes(out)

    def send_can(self, can_id: int, data: bytes):
        if not self.is_open:
            raise RuntimeError("USB-CAN 未连接")

        record = build_standard_data_record(can_id, data)
        with self._tx_lock:
            assert self.ser is not None
            self.ser.write(record)
            self.ser.flush()
        self.on_raw("TX", record)

    def send_ha8(self, payload: bytes, can_id: int = DEFAULT_TX_ID):
        """
        Send one complete HA8 packet through Classical CAN.
        Payloads >8 bytes are split into consecutive 0x6A0 frames.
        The whole HA8 command is protected by a lock so frames cannot interleave.
        """
        if not payload:
            return
        if not self.is_open:
            raise RuntimeError("USB-CAN 未连接")

        chunks = [payload[i:i + 8] for i in range(0, len(payload), 8)]

        with self._command_lock:
            elapsed = time.monotonic() - self._last_ha8_tx
            if elapsed < self.min_ha8_command_gap_s:
                time.sleep(self.min_ha8_command_gap_s - elapsed)

            # One 20-byte USB-CAN command per CDC write.
            # Ping/query fit in one CAN frame, but motion packets are >8 bytes.
            # Keeping every CAN fragment as its own CDC transaction avoids adapters
            # that only execute the first 20-byte command in a concatenated write.
            with self._tx_lock:
                assert self.ser is not None
                for index, chunk in enumerate(chunks):
                    record = build_standard_data_record(can_id, chunk)
                    self.ser.write(record)
                    self.ser.flush()
                    self.on_raw("TX", record)
                    if index + 1 < len(chunks):
                        time.sleep(0.001)

            self._last_ha8_tx = time.monotonic()

    def _reader_loop(self):
        try:
            while self._running and self.ser is not None:
                data = self.ser.read(256)
                if not data:
                    continue

                self.on_raw("RX_BYTES", data)
                self._rxbuf.extend(data)
                self._parse_rx_buffer()

        except Exception as exc:
            if self._running:
                self.on_error(exc)

    def _parse_rx_buffer(self):
        """
        Records are fixed 20 bytes. To recover from an unexpected stray byte,
        scan for a plausible record start: type 0x01 and DLC<=8.
        """
        while len(self._rxbuf) >= 20:
            if self._rxbuf[0] != 0x01 or self._rxbuf[11] > 8:
                del self._rxbuf[0]
                continue

            candidate = bytes(self._rxbuf[:20])
            try:
                frame = parse_standard_data_record(candidate)
            except ValueError:
                del self._rxbuf[0]
                continue

            del self._rxbuf[:20]
            self.on_raw("RX", candidate)
            self.on_frame(frame)