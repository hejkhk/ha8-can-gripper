import sys
import pathlib
import types
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
try:
    import serial
except ImportError:
    serial=types.ModuleType('serial')
    serial.Serial=object
    serial.PARITY_NONE='N'
    sys.modules['serial']=serial

from usb_can_cdc import UsbCanCdc, build_standard_data_record, parse_standard_data_record

class TransportTests(unittest.TestCase):
    def test_roundtrip_fixed_record(self):
        payload=bytes.fromhex('12 4C 01 01 00 60')
        data=build_standard_data_record(0x6A0,payload)
        self.assertEqual(data.hex(' ').upper(),
                         '01 A0 06 00 00 00 00 00 00 00 00 06 12 4C 01 01 00 60 00 00')
        frame=parse_standard_data_record(data)
        self.assertEqual(frame.can_id, 0x6A0)
        self.assertEqual(frame.data,payload)

    def test_separate_multi_can_writes(self):
        driver=UsbCanCdc()
        fake=Mock()
        fake.is_open=True
        driver.ser=fake
        driver.send_ha8(bytes(range(21)))
        writes=[x.args[0] for x in fake.write.call_args_list]
        self.assertEqual([len(x) for x in writes],[20,20,20])
        self.assertEqual([parse_standard_data_record(x).dlc for x in writes],[8,8,5])

if __name__=='__main__':
    unittest.main()