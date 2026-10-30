"""Syntax validation for every application module (does not open hardware)."""
from pathlib import Path
import py_compile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class SourceSyntaxTests(unittest.TestCase):
    def test_all_python_modules_compile(self):
        modules = [
            "HA8_UpperComputer.py",
            "ha8_protocol.py",
            "ha8_serial.py",
            "grip_estimator.py",
            "grip_panel.py",
            "auto_grip_panel.py",
            "pressure_validation.py",
            "pressure_lab_panel.py",
            "serial_device_discovery.py",
            "legacy/usb_can_cdc.py",
            "legacy/f103_uart_bridge.py",
        ]
        for name in modules:
            with self.subTest(module=name):
                py_compile.compile(str(ROOT / name), doraise=True)


if __name__ == "__main__":
    unittest.main()
