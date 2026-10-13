# -*- coding: utf-8 -*-
"""Transparent F103C8T6 UART <-> CAN bridge driver for the HA8 tester.

Expected firmware (the earlier 0x6A0/0x6A1 transparent bridge):
- PC UART 115200 8N1 -> F103 UART1 -> standard CAN 0x6A0, 1 Mbps.
- CAN standard 0x6A1 -> F103 UART1 -> PC UART raw bytes.
- NO USB-CAN CDC 20-byte record format on this connection.

The UART stream does not preserve CAN frame IDs, DLC or boundaries.  CAN frames
reported via on_frame are SYNTHETIC feedback chunks so that the shared HA8
response reassembler can be used unchanged.  They are not a CAN bus trace.
"""

from __future__ import annotations

import threading
import time
import serial

from usb_can_cdc import CanFrame, DEFAULT_TX_ID, DEFAULT_RX_ID


class F103UartBridge:
    """Backend-compatible with UsbCanCdc: open, close, send_can, send_ha8."""

    def __init__(self, on_frame=None, on_error=None, on_raw=None):
        self.ser: serial.Serial | None = None
        self.on_frame = on_frame or (lambda frame: None)
        self.on_error = on_error or (lambda error: None)
        self.on_raw = on_raw or (lambda direction, data: None)
        self._running = False
        self._reader_thread: threading.Thread | None = None
        self._tx_lock = threading.Lock()
        self._command_lock = threading.Lock()
        self._last_ha8_tx = 0.0
        self.min_ha8_command_gap_s = 0.008
        self.baudrate = 115200

    @property
    def is_open(self):
        return self.ser is not None and self.ser.is_open

    def open(self, port: str, baudrate: int = 115200):
        self.close()
        baudrate = int(baudrate)
        if baudrate <= 0:
            raise ValueError('串口波特率必须为正数')
        self.ser = serial.Serial(
            port=port, baudrate=baudrate, bytesize=8,
            parity=serial.PARITY_NONE, stopbits=1,
            timeout=0.03, write_timeout=1.0,
        )
        self.baudrate = baudrate
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

    def send_ha8(self, payload: bytes, can_id: int = DEFAULT_TX_ID):
        """Send one complete HA8 request as raw UART bytes; MCU does CAN split."""
        if can_id != DEFAULT_TX_ID:
            raise ValueError('F103 透明桥接固件固定发 CAN ID 0x6A0，不支持设置其他 ID')
        if not payload:
            return
        if not self.is_open:
            raise RuntimeError('STM32F103 串口未连接')
        with self._command_lock:
            elapsed = time.monotonic() - self._last_ha8_tx
            if elapsed < self.min_ha8_command_gap_s:
                time.sleep(self.min_ha8_command_gap_s - elapsed)
            with self._tx_lock:
                ser = self.ser
                if ser is None:
                    raise RuntimeError('STM32F103 串口已断开')
                ser.write(payload)
                ser.flush()
            self._last_ha8_tx = time.monotonic()
            self.on_raw('TX_UART', bytes(payload))

    def send_can(self, can_id: int, data: bytes):
        """Raw data on a fixed CAN ID. MCU firmware chooses the actual DLC.

        UART bridging does not expose CAN frame boundaries or arbitrary IDs.
        """
        if can_id != DEFAULT_TX_ID:
            raise ValueError('F103 桥接固件只能发送 CAN 0x6A0；其他 ID 需要修改固件')
        if not (1 <= len(data) <= 8):
            raise ValueError('发送 CAN 数据长度必须是 1~8 字节')
        self.send_ha8(data, can_id)

    def _reader_loop(self):
        try:
            while self._running and self.ser is not None:
                data = self.ser.read(128)
                if not data:
                    continue
                self.on_raw('RX_UART', data)
                # UART has no physical CAN segmentation; only virtual chunks.
                for i in range(0, len(data), 8):
                    self.on_frame(CanFrame(can_id=DEFAULT_RX_ID, data=bytes(data[i:i + 8])))
        except Exception as exc:
            if self._running:
                self.on_error(exc)