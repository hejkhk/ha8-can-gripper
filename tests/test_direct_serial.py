# -*- coding: utf-8 -*-
"""Off-hardware validation for the direct UART backend."""
import unittest
from unittest.mock import patch
from ha8_serial import HA8SerialTransport

class FakeSerial:
    def __init__(self, *args, **kwargs):
        self.is_open = True
        self.out = []
    def reset_input_buffer(self): pass
    def write(self, data):
        self.out.append(bytes(data))
        return len(data)
    def flush(self): pass
    def read(self, n):
        return b""
    def close(self): self.is_open = False

class DirectSerialTests(unittest.TestCase):
    def test_ping_complete_frame_is_sent_unchanged(self):
        callback_data = []
        with patch("ha8_serial.serial.Serial", side_effect=FakeSerial):
            t = HA8SerialTransport(on_raw=lambda direction,data: callback_data.append((direction,data)))
            try:
                t.open("COM_TEST")
                t.send_ha8(bytes.fromhex("12 4C 01 01 00 60"))
                self.assertEqual(t.ser.out, [bytes.fromhex("12 4C 01 01 00 60")])
                self.assertEqual(callback_data[-1][0], "TX")
            finally:
                t.close()

    def test_bad_checksum_rejected(self):
        t=HA8SerialTransport()
        with self.assertRaises(ValueError):
            t.send_ha8(bytes.fromhex("12 4C 01 01 00 00"))

    def test_long_packet_not_chunked(self):
        from ha8_protocol import HA8Protocol
        f = HA8Protocol.move(
            servo_id=0,angle_deg=180, multiturn=True,mode="velocity",
            velocity_dps=120,t_acc_ms=200,t_dec_ms=200,power_mw=5000
        )
        self.assertGreater(len(f),8)
        with patch("ha8_serial.serial.Serial", side_effect=FakeSerial):
            t=HA8SerialTransport()
            try:
                t.open("COM_TEST")
                t.send_ha8(f)
                self.assertEqual(t.ser.out,[f])
            finally:
                t.close()
if __name__ == "__main__":
    unittest.main()
