# -*- coding: utf-8 -*-
"""Simulated serial ports verify safe, deterministic, protocol-based COM detection."""
import os
import unittest
from unittest.mock import patch

from ha8_protocol import HA8Protocol
from serial_device_discovery import (PortIdentity, classify_f103_stream,
                                    classify_ha8_reply, probe_port, discover_ports,
                                    unique_selection)
from HA8_UpperComputer import HA8UpperComputer


F103 = b"P,12,120,1744,1405,0\r\nP,13,130,1746,1406,0\r\n"
PONG = b"\x05\x1c\x01\x01\x00\x23"


class FakeClock:
    def __init__(self):
        self.current = 0.0

    def __call__(self):
        return self.current

    def advance(self, duration=0.08):
        self.current += duration


class FakePort:
    def __init__(self, clock, passive=b"", pong=b"", fail=False):
        self.clock = clock
        self.passive = passive
        self.pong = pong
        self.respond = False
        self.writes = []
        self.closed = False
        self.fail = fail

    def __enter__(self):
        if self.fail:
            raise OSError("Port busy")
        return self

    def __exit__(self, *args):
        self.closed = True

    def read(self, size):
        self.clock.advance()
        if self.passive:
            data, self.passive = self.passive[:size],self.passive[size:]
            return data
        if self.respond and self.pong:
            data, self.pong = self.pong[:size], self.pong[size:]
            return data
        return b""

    def write(self, data):
        self.writes.append(bytes(data))
        self.respond = True
        return len(data)

    def flush(self):
        pass


class PortDiscoveryTests(unittest.TestCase):
    def test_pressure_requires_two_valid_sequential_frames(self):
        self.assertTrue(classify_f103_stream(F103))
        self.assertFalse(classify_f103_stream(F103.splitlines()[0]+b"\n"))
        self.assertFalse(classify_f103_stream(b"P,12,120,1744,1405,0\nP,40,130,1746,1406,0\n"))
        self.assertFalse(classify_f103_stream(b"random log and untrusted strings"))

    def test_ping_requires_correct_header_checksum_id(self):
        self.assertTrue(classify_ha8_reply(b"\x01"+PONG,0))
        self.assertFalse(classify_ha8_reply(PONG,1))
        self.assertFalse(classify_ha8_reply(PONG[:-1]+b"\x00",0))
        self.assertFalse(classify_ha8_reply(HA8Protocol.ping(0),0))

    def test_pressure_stream_never_gets_ha8_command(self):
        clock=FakeClock()
        port=FakePort(clock,passive=F103)
        result=probe_port("COM4",serial_factory=lambda **kw:port,now=clock)
        self.assertEqual(result.kind,"pressure")
        self.assertEqual(port.writes,[])
        self.assertTrue(port.closed)

    def test_silent_ha8_only_gets_ping(self):
        clock=FakeClock()
        port=FakePort(clock,pong=PONG)
        result=probe_port("COM6",servo_ids=(0,),serial_factory=lambda **kw:port,now=clock)
        self.assertEqual(result.kind,"ha8")
        self.assertEqual(result.servo_id,0)
        self.assertEqual(port.writes,[HA8Protocol.ping(0)])
        self.assertTrue(port.closed)

    def test_unknown_active_port_never_gets_ping(self):
        clock=FakeClock()
        port=FakePort(clock,passive=b"strange device boot output")
        result=probe_port("COM8",serial_factory=lambda **kw:port,now=clock)
        self.assertEqual(result.kind,"unknown")
        self.assertEqual(port.writes,[])

    def test_wrong_ping_reply_never_marked_ha8(self):
        clock=FakeClock()
        port=FakePort(clock,pong=b"garbage")
        result=probe_port("COM7",serial_factory=lambda **kw:port,now=clock)
        self.assertEqual(result.kind,"unknown")

    def test_busy_not_misclassified(self):
        clock=FakeClock()
        port=FakePort(clock,fail=True)
        result=probe_port("COM1",serial_factory=lambda **kw:port,now=clock)
        self.assertEqual(result.kind,"busy")

    def test_duplicates_are_ambiguous_and_keep_manual_fallback(self):
        result=unique_selection([
            PortIdentity("COM4","pressure"),
            PortIdentity("COM5","pressure"),
            PortIdentity("COM6","ha8",0),
            PortIdentity("COM7","unknown")])
        self.assertIsNone(result["pressure"])
        self.assertEqual(result["ha8"].port,"COM6")

    def test_reject_excess_port_count(self):
        with self.assertRaises(ValueError):
            discover_ports([f"COM{i}" for i in range(19)])


@unittest.skipUnless(os.name=="nt" or os.environ.get("DISPLAY"),"Display required")
class PortDiscoveryGuiTests(unittest.TestCase):
    def test_one_click_button_and_two_roles(self):
        app=HA8UpperComputer()
        app.withdraw()
        try:
            self.assertTrue(app.detect_btn.winfo_exists())
            self.assertIn("自动",app.detect_btn.cget("text"))
            self.assertFalse(app.discovery_busy)
            self.assertEqual(app.tx_ha8_count,0)
            self.assertFalse(app.pressure_lab.link.is_open)
            self.assertFalse(app.transport.is_open)
        finally:
            app.destroy()

    def test_unknown_ports_do_not_attempt_connections(self):
        app=HA8UpperComputer()
        app.withdraw()
        try:
            with patch.object(app,"connect") as connect, patch.object(app.pressure_lab,"connect_port") as pconnect:
                app._finish_discovery([PortIdentity("COM1","unknown")],None)
            connect.assert_not_called()
            pconnect.assert_not_called()
            self.assertIn("未唯一识别",app.detect_status.get())
        finally:
            app.destroy()


if __name__=="__main__":
    unittest.main()
