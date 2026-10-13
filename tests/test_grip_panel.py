# -*- coding: utf-8 -*-
"""Smoke-test the experimental panel when a graphical display is available."""
from pathlib import Path
import os
import sys
import tkinter as tk
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from grip_panel import GripPanel


@unittest.skipUnless(os.environ.get('DISPLAY') or os.name == 'nt', 'No GUI display available')
class GripPanelTests(unittest.TestCase):
    def test_create_and_display_sample(self):
        root = tk.Tk()
        root.withdraw()
        class FakeTransport:
            is_open = True
        class FakeApp:
            transport = FakeTransport()
            monitor_running = True
            monitor_vars = {k: tk.StringVar(master=root, value='—') for k in ('torque_ref','grip_state')}
            def servo_id(self):
                return 0
            def log(self, message):
                pass
        try:
            panel = GripPanel(root, FakeApp())
            panel.pack()
            panel.on_monitor(0, {'current_ma': 350, 'angle_deg': 10, 'status': 0})
            self.assertTrue(panel.status_var.get())
            self.assertEqual(panel.current_var.get(), '0.350 A')
            panel.stop()
            panel.destroy()
            root.update_idletasks()
        finally:
            root.destroy()


if __name__ == '__main__':
    unittest.main()