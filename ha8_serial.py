# -*- coding: utf-8 -*-
"""HA8 native UART transport for the official USB servo adapter.

The official adapter presents a Windows COM port. HA8 requests are passed
unchanged as whole byte frames; responses are arbitrary serial byte chunks.
No USB-CAN vendor framing, STM32 firmware, CTS100M, or CAN IDs are involved.
"""
from __future__ import annotations

import threading
import time

import serial


class HA8SerialTransport:
    def __init__(self, on_bytes=None, on_error=None, on_raw=None):
        self.on_bytes = on_bytes or (lambda data: None)
        self.on_error = on_error or (lambda exc: None)
        self.on_raw = on_raw or (lambda direction, data: None)
        self.ser = None
        self._running = False
        self._read_thread = None
        self._send_lock = threading.RLock()
        self._last_command_time = 0.0
        self.command_gap_s = 0.008

    @property
    def is_open(self):
        return self.ser is not None and self.ser.is_open

    def open(self, port: str, baudrate: int = 115200):
        self.close()
        baudrate = int(baudrate)
        if baudrate <= 0:
            raise ValueError("串口波特率必须为正数")
        new_serial = serial.Serial(
            port=port, baudrate=baudrate, bytesize=8,
            parity=serial.PARITY_NONE, stopbits=1,
            timeout=0.03, write_timeout=1.0,
        )
        try:
            new_serial.reset_input_buffer()
        except Exception:
            new_serial.close()
            raise
        self.ser = new_serial
        self._running = True
        self._read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._read_thread.start()

    def close(self):
        self._running = False
        old = self.ser
        self.ser = None
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        worker = self._read_thread
        self._read_thread = None
        if worker is not None and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=0.3)

    def send_ha8(self, payload: bytes):
        if len(payload) < 5 or payload[:2] != b"\x12\x4C":
            raise ValueError("发送内容必须是完整 HA8 请求帧，原始调试请使用 send_raw")
        if len(payload) != payload[3] + 5:
            raise ValueError("HA8 请求的 LEN 与实际长度不一致")
        if (sum(payload[:-1]) & 0xff) != payload[-1]:
            raise ValueError("HA8 请求校验和错误")
        self.send_raw(payload)

    def send_raw(self, payload: bytes):
        if not payload:
            raise ValueError("不能发送空数据")
        with self._send_lock:
            if not self.is_open:
                raise RuntimeError("官方舵机 USB 串口未连接")
            delta = time.monotonic() - self._last_command_time
            if delta < self.command_gap_s:
                time.sleep(self.command_gap_s - delta)
            ser = self.ser
            if ser is None or not ser.is_open:
                raise RuntimeError("串口已断开")
            written = ser.write(payload)
            if written != len(payload):
                raise IOError(f"串口短写：{written}/{len(payload)}")
            ser.flush()
            self._last_command_time = time.monotonic()
            self.on_raw("TX", bytes(payload))

    def _read_loop(self):
        try:
            while self._running:
                ser = self.ser
                if ser is None:
                    break
                try:
                    chunk = ser.read(256)
                except (serial.SerialException, OSError):
                    if not self._running:
                        return
                    raise
                if not chunk:
                    continue
                self.on_raw("RX", bytes(chunk))
                self.on_bytes(bytes(chunk))
        except Exception as exc:
            if self._running:
                self.on_error(exc)
