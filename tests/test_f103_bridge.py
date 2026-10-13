"""Offline bridge transport tests; do not require a physical STM32/USB-TTL."""
import unittest
from unittest.mock import Mock
import sys
import types
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import serial
except ImportError:
    serial = types.ModuleType("serial")
    serial.Serial = object
    serial.PARITY_NONE = "N"
    sys.modules["serial"] = serial

from f103_uart_bridge import F103UartBridge
from ha8_protocol import HA8Protocol, ResponseStreamParser


class F103BridgeTests(unittest.TestCase):
    def test_ping_is_raw_uart_not_usb_can_record(self):
        bridge = F103UartBridge()
        fake = Mock(is_open=True)
        bridge.ser = fake
        bridge.send_ha8(HA8Protocol.ping(0))
        fake.write.assert_called_once_with(bytes.fromhex('12 4C 01 01 00 60'))

    def test_long_motion_is_one_uart_write(self):
        bridge = F103UartBridge()
        fake = Mock(is_open=True)
        bridge.ser = fake
        packet = HA8Protocol.move(0, 600, multiturn=True, mode='velocity')
        self.assertGreater(len(packet), 8)
        bridge.send_ha8(packet)
        fake.write.assert_called_once_with(packet)

    def test_only_fixed_can_id_supported(self):
        bridge = F103UartBridge()
        fake = Mock(is_open=True)
        bridge.ser = fake
        with self.assertRaises(ValueError):
            bridge.send_can(0x123, b'abc')
        bridge.send_can(0x6A0, b'abc')
        fake.write.assert_called_once_with(b'abc')

    def test_feedback_can_be_reassembled(self):
        received = []
        bridge = F103UartBridge(on_frame=received.append)
        bridge.ser = Mock(is_open=True)
        bridge._running = True
        bridge.ser.read.side_effect = [bytes.fromhex('05 1C'), bytes.fromhex('01 01 00 23')]
        # Stop after second read without making thread/COM.
        calls = iter([bytes.fromhex('05 1C'), bytes.fromhex('01 01 00 23')])
        def read(_):
            value = next(calls)
            if value == bytes.fromhex('01 01 00 23'):
                bridge._running = False
            return value
        bridge.ser.read.side_effect = read
        bridge._reader_loop()
        parser = ResponseStreamParser()
        frames = []
        for item in received:
            frames.extend(parser.feed(item.data))
        self.assertEqual(frames, [bytes.fromhex('05 1C 01 01 00 23')])


if __name__ == '__main__':
    unittest.main()