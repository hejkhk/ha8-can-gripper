# -*- coding: utf-8 -*-
"""GUI layout checks run under Xvfb in CI, never send real serial commands."""
import os
import tkinter as tk
import unittest
from unittest.mock import patch

from HA8_UpperComputer import HA8UpperComputer


@unittest.skipUnless(os.environ.get("DISPLAY") or os.name == "nt",
                     "GUI test requires a display")
class SimpleLayoutTests(unittest.TestCase):
    def test_starts_with_single_basic_tab_and_can_restore_tools(self):
        app = HA8UpperComputer()
        app.withdraw()
        try:
            self.assertEqual(app.nb.tab(app.tab_auto_grip, "text"), "夹爪控制")
            self.assertEqual(app.nb.select(), str(app.tab_auto_grip))
            self.assertEqual(app.nb.tab(app.tab_control, "state"), "hidden")
            self.assertEqual(app.connection_details.winfo_manager(), "")
            self.assertEqual(app.log_box.winfo_manager(), "")
            self.assertEqual(app.auto_grip_panel.advanced_settings.winfo_manager(), "")
            app.toggle_advanced_mode()
            self.assertEqual(app.nb.tab(app.tab_control, "state"), "normal")
            self.assertEqual(app.connection_details.winfo_manager(), "pack")
            self.assertEqual(app.log_box.winfo_manager(), "pack")
            app.nb.select(app.tab_control)
            app.toggle_advanced_mode()
            self.assertEqual(app.nb.select(), str(app.tab_auto_grip))
            self.assertEqual(app.nb.tab(app.tab_control, "state"), "hidden")
        finally:
            app.destroy()

    def test_easy_panel_exposes_two_limits_and_three_actions(self):
        app = HA8UpperComputer()
        app.withdraw()
        try:
            panel = app.auto_grip_panel
            self.assertEqual(panel.grip_min.get(), "")
            self.assertEqual(panel.open_max.get(), "")
            self.assertEqual(len(panel.param_entries), 5)
            self.assertTrue(panel.grip_btn.instate(["disabled"]))
            self.assertTrue(panel.open_btn.instate(["disabled"]))
            self.assertTrue(panel.stop_btn.winfo_exists())
            panel.toggle_settings()
            self.assertEqual(panel.advanced_settings.winfo_manager(), "pack")
            panel.toggle_settings()
            self.assertEqual(panel.advanced_settings.winfo_manager(), "")
        finally:
            app.destroy()

    def test_connect_starts_read_only_monitor_without_motion(self):
        app = HA8UpperComputer()
        app.withdraw()
        class DummyTransport:
            is_open = False
            sent = []
            def open(self, port, baudrate):
                self.is_open = True
            def send_ha8(self, payload):
                self.sent.append(bytes(payload))
            def close(self):
                self.is_open = False
        fake = DummyTransport()
        try:
            app.transport = fake
            app.port_var.set("COM_TEST")
            app.connect()
            self.assertTrue(app.monitor_running)
            self.assertEqual(app.monitor_period_var.get(), "100")
            self.assertEqual(len(fake.sent), 1)
            self.assertEqual(fake.sent[0][2], 0x16)  # monitor, NOT movement
            app.disconnect()
            self.assertFalse(app.monitor_running)
        finally:
            app.destroy()


if __name__ == "__main__":
    unittest.main()
