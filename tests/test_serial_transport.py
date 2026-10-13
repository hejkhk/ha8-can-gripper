# -*- coding: utf-8 -*-
"""Offline checks for the direct HA8 UART transport (no hardware required)."""
import pathlib
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ha8_serial import HA8SerialTransport
from ha8_protocol import HA8Protocol, ResponseStreamParser

class FakeSerial:
    def __init__(self):
        self.is_open = True
        self.writes = []
        self.incoming = bytearray()
    def reset_input_buffer(self):
        self.incoming.clear()
    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)
    def flush(self):
        pass
    def read(self, count):
        if not self.incoming:
            time.sleep(0.005)
            return b""
        data = bytes(self.incoming[:count])
        del self.incoming[:count]
        return data
    def close(self):
        self.is_open = False

class HA8SerialTests(unittest.TestCase):
    def test_ping_exact_uart_bytes(self):
        fake = FakeSerial()
        transport = HA8SerialTransport()
        with patch("ha8_serial.serial.Serial", return_value=fake):
            transport.open("TEST_COM", baudrate=115200)
            transport.send_ha8(HA8Protocol.ping(0))
            transport.close()
        self.assertEqual(fake.writes, [bytes.fromhex("12 4C 01 01 00 60")])

    def test_long_motion_not_split_into_can_frames(self):
        fake = FakeSerial()
        transport = HA8SerialTransport()
        with patch("ha8_serial.serial.Serial", return_value=fake):
            transport.open("TEST_COM")
            motion = HA8Protocol.move(0, 360, multiturn=True, mode="velocity")
            self.assertGreater(len(motion), 8)
            transport.send_ha8(motion)
            transport.close()
        self.assertEqual(fake.writes, [motion])

    def test_receive_stream_can_be_split(self):
        frame = bytes.fromhex("05 1C 01 01 00 23")
        parser = ResponseStreamParser()
        self.assertEqual(parser.feed(frame[:2]), [])
        self.assertEqual(parser.feed(frame[2:4]), [])
        self.assertEqual(parser.feed(frame[4:]), [frame])

    def test_reject_bad_checksum_without_serial_write(self):
        fake = FakeSerial()
        transport = HA8SerialTransport()
        transport.ser = fake
        with self.assertRaises(ValueError):
            transport.send_ha8(bytes.fromhex("12 4C 01 01 00 61"))
        self.assertEqual(fake.writes, [])
        transport.close()

if __name__ == "__main__":
    unittest.main()
