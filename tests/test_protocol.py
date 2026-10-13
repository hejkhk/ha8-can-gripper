import sys
import pathlib
import struct
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ha8_protocol import (
    HA8Protocol, CMD_SYNC, build_request, verify_response,
    decode_response, ResponseStreamParser,
)


class ProtocolTests(unittest.TestCase):
    def test_ping_request_and_reply(self):
        self.assertEqual(HA8Protocol.ping(0).hex(' ').upper(), '12 4C 01 01 00 60')
        rx = bytes.fromhex('05 1C 01 01 00 23')
        self.assertTrue(verify_response(rx))
        self.assertTrue(decode_response(rx).fields['online'])

    def test_multiframe_response_parser(self):
        rx = bytes.fromhex('05 1C 0A 03 00 FD FF 2A')
        p = ResponseStreamParser()
        self.assertEqual(p.feed(rx[:2]), [])
        self.assertEqual(p.feed(rx[2:]), [rx])
        self.assertAlmostEqual(decode_response(rx).fields['angle_deg'], -0.3)

    def test_safe_reset(self):
        self.assertEqual(HA8Protocol.reset_user_data(0), bytes.fromhex('12 4C 02 01 00 61'))
        self.assertEqual(HA8Protocol.begin_async(), bytes.fromhex('12 4C 12 00 70'))
        self.assertEqual(HA8Protocol.end_async(True), bytes.fromhex('12 4C 13 01 01 73'))

    def test_six_sync_motion_layouts(self):
        for multi in (False, True):
            for mode in ('simple', 'interval', 'velocity'):
                frame = HA8Protocol.sync_motion([(0, 20), (1, -20)],
                                                multiturn=multi, mode=mode,
                                                velocity_dps=60, interval_ms=2000,
                                                t_acc_ms=200, t_dec_ms=200,
                                                power_mw=1000)
                self.assertEqual(frame[:2], bytes.fromhex('12 4C'))
                self.assertEqual(frame[2], CMD_SYNC)
                self.assertEqual(frame[3], len(frame)-5)
                self.assertEqual(frame[6], 2)  # number of servos
                self.assertEqual(frame[-1], sum(frame[:-1]) & 255)
                self.assertEqual(len(frame[7:-1]), frame[5]*2)

    def test_sync_monitor(self):
        frame=HA8Protocol.sync_monitor([0, 3, 6])
        self.assertEqual(frame[2],CMD_SYNC)
        self.assertEqual(frame[4:10],bytes([0x16,1,3,0,3,6]))

    def test_write_ack(self):
        # write response ID=0, address=49, result=1
        packet = bytes.fromhex('05 1C 04 03 00 31 01')
        packet += bytes([sum(packet)&255])
        rsp=decode_response(packet)
        self.assertEqual(rsp.fields['address'],49)
        self.assertTrue(rsp.fields['write_ok'])

    def test_single_turn_boundary(self):
        with self.assertRaises(ValueError):
            HA8Protocol.sync_motion([(0, 600)], multiturn=False)


if __name__ == '__main__':
    unittest.main()