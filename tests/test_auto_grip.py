# -*- coding: utf-8 -*-
"""Headless regression checks; never a substitute for physical stop validation."""
import time
import unittest

from auto_grip_panel import AutoGripPanel
from ha8_protocol import HA8Protocol, STOP_HOLD


class Value:
    def __init__(self, value):
        self.value = str(value)
    def get(self):
        return self.value
    def set(self, value):
        self.value = str(value)


class FakeApp:
    def __init__(self, selected_id=7):
        self.selected_id = selected_id
        self.sent = []
        self.transport = type("Transport", (), {"is_open": True})()
        self.monitor_running = True
    def servo_id(self):
        return self.selected_id
    def send_ha8(self, frame, label):
        self.sent.append((frame, label))
    def log(self, message):
        pass


def make_panel():
    # Deliberately avoid creating Tk widgets or opening a COM port.
    panel = object.__new__(AutoGripPanel)
    panel.app = FakeApp()
    panel.phase = "gripping"
    panel.active_servo_id = 3
    panel.servo_id = 3
    panel.estop_latched = False
    panel._stop_sent = False
    panel.started = time.monotonic()
    panel.last_at = time.monotonic()
    panel.status_bits = 0
    panel.detector = None
    panel.hold_power = Value(500)
    panel.status_text = Value("")
    panel.current_text = Value("")
    panel.angle_text = Value("")
    panel.angle = 20.0
    panel.current = 0.0
    return panel


class AutoGripSafetyTests(unittest.TestCase):
    def test_stop_always_targets_session_servo(self):
        panel = make_panel()
        panel._send_hold("test stop")
        self.assertEqual(len(panel.app.sent), 1)
        self.assertEqual(panel.app.sent[0][0], HA8Protocol.stop(3, STOP_HOLD, 500))
        self.assertTrue(panel._stop_sent)

    def test_error_bit_blocks_start(self):
        panel = make_panel()
        panel.phase = None
        panel.active_servo_id = None
        panel.servo_id = 7
        panel.status_bits = 0x02
        with self.assertRaises(RuntimeError):
            panel._preflight()

    def test_error_bit_requests_stop_during_motion(self):
        panel = make_panel()
        panel.app.selected_id = 3
        panel.on_monitor(3, {"angle_deg": 20.0, "current_ma": 100, "status": 0x02})
        self.assertTrue(panel.estop_latched)
        self.assertEqual(panel.app.sent[-1][0], HA8Protocol.stop(3, STOP_HOLD, 500))

    def test_disconnection_during_motion_latches(self):
        panel = make_panel()
        panel.disconnected()
        self.assertTrue(panel.estop_latched)
        self.assertIsNone(panel.phase)
        self.assertIsNone(panel.last_at)

    def test_id_change_triggers_stop_on_original_servo(self):
        panel = make_panel()
        panel.app.selected_id = 7
        panel.after = lambda ms, callback: "mock-job"
        panel._tick()
        self.assertTrue(panel.estop_latched)
        self.assertEqual(panel.app.sent[-1][0], HA8Protocol.stop(3, STOP_HOLD, 500))


if __name__ == "__main__":
    unittest.main()
