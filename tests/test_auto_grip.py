# -*- coding: utf-8 -*-
"""Headless regression checks; never a substitute for physical stop validation."""
import time
import unittest
from unittest.mock import patch

from auto_grip_panel import AutoGripPanel
from ha8_protocol import HA8Protocol, STOP_HOLD
from grip_estimator import GripDetector, GripSample, GripState


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
    def toggle_monitor(self):
        self.monitor_running = not self.monitor_running


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
    panel.session_hold = 500
    panel.session_min = 10.0
    panel.session_max = 90.0
    panel._stop_at = None
    panel._stop_previous = None
    panel._stop_stable_count = 0
    panel._stop_reason = ''
    panel.param_entries = []
    panel.feedback_text = Value('')
    panel.grip_min = Value('10')
    panel.open_max = Value('90')
    panel.speed = Value('10')
    panel.power = Value('1500')
    return panel


class AutoGripSafetyTests(unittest.TestCase):
    def test_stop_always_targets_session_servo(self):
        panel = make_panel()
        panel._send_hold("test stop")
        self.assertEqual(len(panel.app.sent), 1)
        self.assertEqual(panel.app.sent[0][0], HA8Protocol.stop(3, STOP_HOLD, 500))
        self.assertTrue(panel._stop_sent)

    def test_stop_enters_observation_until_feedback_stable(self):
        panel = make_panel()
        panel._send_hold("到达限位")
        self.assertEqual(panel.phase, "stopping")
        self.assertTrue(panel._stop_sent)
        self.assertIn("正在观察", panel.status_text.get())
        for i in range(1, 6):
            with patch("auto_grip_panel.time.monotonic",
                       return_value=panel._stop_at + 0.12 * i):
                panel.on_monitor(3, {"angle_deg": 20.0, "current_ma": 110, "status": 0})
        self.assertIsNone(panel.phase)
        self.assertFalse(panel._stop_sent)
        self.assertFalse(panel.estop_latched)
        self.assertIn("仅软件观测", panel.status_text.get())

    def test_missing_stop_feedback_latches_unconfirmed(self):
        panel = make_panel()
        panel._send_hold("测试")
        panel.after = lambda ms, callback: "mock-job"
        with patch("auto_grip_panel.time.monotonic",
                   return_value=panel._stop_at + 2.5):
            panel._tick()
        self.assertTrue(panel.estop_latched)
        self.assertIsNone(panel.phase)
        self.assertIn("停止未确认", panel.status_text.get())

    def test_editing_limits_does_not_change_active_target(self):
        panel = make_panel()
        panel.phase = "opening"
        panel.active_servo_id = 3
        panel.open_max.set("300")
        panel.session_max = 90.0
        panel.on_monitor(3, {"angle_deg": 89.5, "current_ma": 100, "status": 0})
        self.assertEqual(panel.phase, "stopping")
        self.assertEqual(panel.app.sent[-1][0], HA8Protocol.stop(3, STOP_HOLD, 500))

    def test_monitor_toggle_from_grip_page_uses_shared_monitor(self):
        panel = make_panel()
        panel.phase = None
        panel.app.monitor_running = False
        panel.toggle_panel_monitor()
        self.assertTrue(panel.app.monitor_running)
        panel.toggle_panel_monitor()
        self.assertFalse(panel.app.monitor_running)

    def test_invalid_angle_limits_cannot_start(self):
        panel = make_panel()
        panel.grip_min.set("90")
        panel.open_max.set("10")
        with self.assertRaises(ValueError):
            panel._parameters()

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

    def test_grip_detector_latches_command_error(self):
        detector = GripDetector()
        detector.arm()
        result = detector.observe(GripSample(time.monotonic(), 10.0, 0.3, 0x02))
        self.assertEqual(result.state, GripState.FAULT)

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
