"""Tests for the VVM Monitor application"""

import unittest
import os
import logging
from unittest.mock import patch
from vvm_to_signalk.vvm_monitor import VVMConfig, VesselViewMobileDataRecorder

class TestVVMConfig(unittest.TestCase):
    """Test the VVMConfig class"""

    def test_default_config(self):
        """Test that the default configuration is loaded correctly"""
        config = VVMConfig()
        self.assertEqual(config.logging_level, logging.INFO)
        self.assertEqual(config.logging_file, "./logs/vvm_monitor.log")
        self.assertEqual(config.logging_keep, 5)
        self.assertFalse(config.healthcheck_enable)

    def test_read_dict(self):
        """Test that the configuration is loaded correctly from a dictionary"""
        data = {
            'signalk': {
                'websocket-url': 'ws://localhost:3000/signalk/v1/stream',
                'username': 'testuser',
                'password': 'testpassword'
            },
            'ble-device': {
                'name': 'TestDevice',
                'address': '00:11:22:33:44:55'
            },
            'csv': {
                'enabled': True,
                'filename': '/tmp/test.csv'
            },
            'logging': {
                'level': 'DEBUG',
                'file': '/tmp/test.log',
                'keep': 10
            }
        }
        config = VVMConfig(data)
        self.assertEqual(config.signalk.websocket_url, 'ws://localhost:3000/signalk/v1/stream')
        self.assertEqual(config.signalk.username, 'testuser')
        self.assertEqual(config.signalk.password, 'testpassword')
        self.assertEqual(config.bluetooth.device_name, 'TestDevice')
        self.assertEqual(config.bluetooth.device_address, '00:11:22:33:44:55')
        self.assertTrue(config.csv.enabled)
        self.assertEqual(config.csv.filename, '/tmp/test.csv')
        self.assertEqual(config.logging_level, logging.DEBUG)
        self.assertEqual(config.logging_file, '/tmp/test.log')
        self.assertEqual(config.logging_keep, 10)

class TestVesselViewMobileDataRecorder(unittest.TestCase):
    """Test the VesselViewMobileDataRecorder class"""

    @patch('argparse.ArgumentParser.parse_args', return_value=unittest.mock.Mock(signalk_websocket_url='ws://test.com', device_address=None, device_name=None, debug=False, username=None, password=None))
    def test_parse_arguments_signalk_url(self, mock_parse_args):
        config = VVMConfig()
        VesselViewMobileDataRecorder.parse_arguments(config)
        self.assertEqual(config.signalk.websocket_url, 'ws://test.com')

    @patch('argparse.ArgumentParser.parse_args', return_value=unittest.mock.Mock(signalk_websocket_url=None, device_address='AA:BB:CC:DD:EE:FF', device_name=None, debug=False, username=None, password=None))
    def test_parse_arguments_device_address(self, mock_parse_args):
        config = VVMConfig()
        VesselViewMobileDataRecorder.parse_arguments(config)
        self.assertEqual(config.bluetooth.device_address, 'AA:BB:CC:DD:EE:FF')

    @patch('argparse.ArgumentParser.parse_args', return_value=unittest.mock.Mock(signalk_websocket_url=None, device_address=None, device_name='MyDevice', debug=False, username=None, password=None))
    def test_parse_arguments_device_name(self, mock_parse_args):
        config = VVMConfig()
        VesselViewMobileDataRecorder.parse_arguments(config)
        self.assertEqual(config.bluetooth.device_name, 'MyDevice')

    @patch('argparse.ArgumentParser.parse_args', return_value=unittest.mock.Mock(signalk_websocket_url=None, device_address=None, device_name=None, debug=True, username=None, password=None))
    def test_parse_arguments_debug(self, mock_parse_args):
        config = VVMConfig()
        VesselViewMobileDataRecorder.parse_arguments(config)
        self.assertEqual(config.logging_level, logging.DEBUG)

    @patch.dict(os.environ, {'VVM_SIGNALK_URL': 'ws://env.test.com'})
    def test_parse_env_variables_signalk_url(self):
        config = VVMConfig()
        VesselViewMobileDataRecorder.parse_env_variables(config)
        self.assertEqual(config.signalk.websocket_url, 'ws://env.test.com')

    @patch.dict(os.environ, {'VVM_DEVICE_ADDRESS': '11:22:33:44:55:66'})
    def test_parse_env_variables_device_address(self):
        config = VVMConfig()
        VesselViewMobileDataRecorder.parse_env_variables(config)
        self.assertEqual(config.bluetooth.device_address, '11:22:33:44:55:66')

    @patch.dict(os.environ, {'VVM_DEVICE_NAME': 'EnvDevice'})
    def test_parse_env_variables_device_name(self):
        config = VVMConfig()
        VesselViewMobileDataRecorder.parse_env_variables(config)
        self.assertEqual(config.bluetooth.device_name, 'EnvDevice')

    @patch.dict(os.environ, {'VVM_DEBUG': 'true'})
    def test_parse_env_variables_debug_true(self):
        config = VVMConfig()
        VesselViewMobileDataRecorder.parse_env_variables(config)
        self.assertEqual(config.logging_level, logging.DEBUG)

    @patch.dict(os.environ, {'VVM_DEBUG': '1'})
    def test_parse_env_variables_debug_1(self):
        config = VVMConfig()
        VesselViewMobileDataRecorder.parse_env_variables(config)
        self.assertEqual(config.logging_level, logging.DEBUG)

    @patch.dict(os.environ, {'APP_HEALTHCHECK_ENABLE': 'true'})
    def test_parse_env_variables_healthcheck_true(self):
        config = VVMConfig()
        VesselViewMobileDataRecorder.parse_env_variables(config)
        self.assertTrue(config.healthcheck_enable)

    @patch.dict(os.environ, {'APP_HEALTHCHECK_ENABLE': '0'})
    def test_parse_env_variables_healthcheck_false(self):
        config = VVMConfig()
        VesselViewMobileDataRecorder.parse_env_variables(config)
        self.assertFalse(config.healthcheck_enable)

if __name__ == '__main__':
    unittest.main()


import asyncio
from vvm_to_signalk.ble_connection import BleDeviceConnection, BleConnectionConfig, UUIDs
from vvm_to_signalk.data_dictionary import DataDictionary


class RecordingReceiver:
    def __init__(self): self.values = {}; self.faults = []
    async def accept_engine_data(self, item, engine_id, value):
        self.values[(item.id, engine_id)] = value
    def update_active_items(self, ids): pass
    async def accept_fault(self, fault): self.faults.append(fault)


class FakeChar:
    def __init__(self, uuid): self.uuid = uuid


def test_capture_bytes_produce_expected_values():
    async def _run():
        conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})
        rx = RecordingReceiver(); conn.accept_data_receiver(rx)
        conn._dictionary = DataDictionary.load(); conn._max_engines = 4
        conn._active_engine_ids = {1}
        # RPM 600, Voltage 14.523, Oil pressure 295.42 kPa
        conn.notification_handler(FakeChar("00000102-0000-1000-8000-ec55f9f5b963"),
                                  bytearray.fromhex("01005802000000000000"))
        conn.notification_handler(FakeChar("00000104-0000-1000-8000-ec55f9f5b963"),
                                  bytearray.fromhex("e800bb38000000000000"))
        # Fault on 0x201
        conn.notification_handler(FakeChar(UUIDs.DEVICE_201_UUID), bytearray.fromhex("12015704"))
        await asyncio.sleep(0)
        return rx
    rx = asyncio.run(_run())
    assert rx.values[(1, 1)] == 600.0
    assert round(rx.values[(232, 1)], 3) == 14.523
    assert rx.faults and rx.faults[0].fault_key == "1111-Legacy"

def test_vvmconfig_reads_proxy_section():
    from vvm_to_signalk.vvm_monitor import VVMConfig
    cfg = VVMConfig({"proxy": {"enabled": True, "advertised-name": "VVM_X"}})
    assert cfg.proxy.enabled is True
    assert cfg.proxy.advertised_name == "VVM_X"


def test_vvmconfig_proxy_default_off():
    from vvm_to_signalk.vvm_monitor import VVMConfig
    cfg = VVMConfig({})
    assert cfg.proxy.enabled is False
