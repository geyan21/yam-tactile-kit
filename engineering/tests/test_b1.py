"""B1 protocol fault tests; fixtures are synthetic and never physical evidence."""

import copy
import importlib.util
from pathlib import Path
import struct
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"engineering/software"))
from b1_protocol import decode,native_vectors,SETTINGS
spec=importlib.util.spec_from_file_location("b1_driver",ROOT/"engineering/firmware/b1/mlx90393.py")
driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)


def sample():
    return {"type":"sample","protocol":"yam-b1/1","seq":1,"device_us":50000,"scan_us":40000,
            "settings":copy.deepcopy(SETTINGS),"errors":[],"nail_cells":False,
            "sensors":[{"channel":i,"raw_xyz":[-100,200,1000],"temperature_raw":46000,
                        "status":3,"start_us":1000+i*1500,"read_us":15000+i*1000} for i in range(5)]}


class B1Tests(unittest.TestCase):
    def test_signed_nominal_units_and_no_force(self):
        reading=decode(sample())
        self.assertEqual(reading["magnetic_local_ut"][0],[-30,60,484])
        self.assertTrue(reading["valid"]);self.assertIsNone(reading["force_n"])

    def test_missing_head_is_not_clear_contact(self):
        item=sample();item["sensors"][1]=None
        result=decode(item);self.assertFalse(result["valid"]);self.assertIsNone(result["magnetic_local_ut"][1])

    def test_status_fault_is_not_reused_field(self):
        for status in (0,2,0x13,0x0B,0x07,0x83):
            item=sample();item["sensors"][0]["status"]=status
            self.assertFalse(decode(item)["valid"])

    def test_wrong_gain_rejected(self):
        item=sample();item["settings"]["gain_sel"]=0
        with self.assertRaises(ValueError):decode(item)

    def test_unknown_channel_rejected(self):
        item=sample();item["sensors"][0]["channel"]=2
        with self.assertRaises(ValueError):decode(item)

    def test_timestamp_order_rejected(self):
        item=sample();item["sensors"][0]["read_us"]=0
        with self.assertRaises(ValueError):decode(item)

    def test_boolean_count_rejected(self):
        item=sample();item["sensors"][0]["raw_xyz"][0]=True
        with self.assertRaises(ValueError):decode(item)

    def test_rail_and_overrun_rejected(self):
        item=sample();item["sensors"][0]["raw_xyz"][2]=30000
        self.assertFalse(decode(item)["valid"])
        item=sample();item["scan_us"]=50001
        self.assertFalse(decode(item)["valid"])

    def test_broken_nail_wire_retained_as_fault(self):
        item=sample();item.update(nail_cells=True,nail_raw=[0,13200,13200,13200],
            nail_offset_us=[25000,27000,29000,31000],pull_down_ohm=[10000]*2,continuity_ohm=100000)
        result=decode(item)
        self.assertFalse(result["valid"]);self.assertIsNone(result["nail_conductance_us"][0])
        self.assertAlmostEqual(result["nail_conductance_us"][1],100.)

    def test_read_response_status_and_sign(self):
        message=bytes([3])+struct.pack(">Hhhh",46000,-32768,0,32767)
        self.assertEqual(driver.unpack_measurement(message)["raw_xyz"],[-32768,0,32767])
        with self.assertRaises(OSError):driver.unpack_measurement(bytes([2])+message[1:])

    def test_mux_exact_single_branch(self):
        class Bus:
            def writeto(self,address,data):self.payload=data;return len(data)
            def readfrom(self,address,length):return self.payload
        bus=Bus();driver.select(bus,4);self.assertEqual(bus.payload,b"\x10")
        with self.assertRaises(ValueError):driver.select(bus,5)
        class Fault(Bus):
            def readfrom(self,address,length):return b"\x03"
        with self.assertRaises(OSError):driver.select(Fault(),0)

    def test_native_rotation_is_required_before_comparing_heads(self):
        poses=[{"rotation_sensor_to_native":[[0,0,-1],[-1,0,0],[0,1,0]]}]*5
        self.assertEqual(native_vectors([[1,2,3]]*5,poses)[0],[-3,-1,2])


if __name__=="__main__":unittest.main()
