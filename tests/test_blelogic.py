from ble_connection import BleDeviceConnection, BleConnectionConfig, Conversion
from config_decoder import EngineParameter, EngineParameterType
import logging
import unittest
import asyncio
import math
import sys
from bleak import BleakGATTCharacteristic

logger = logging.getLogger(__name__)

class BasicGATTCharacteristic(BleakGATTCharacteristic):
    def __init__(self, uuid, properties, value_handle):
        super().__init__(uuid, None)
        self.uuid = uuid
    
    def add_descriptor(self, value):
        pass
    
    def descriptors(self):
        pass
    
    def get_descriptor(self):
        pass
    
    def handle(self):
        pass
    
    def properties(self):
        pass

    def service_handle(self):
        pass
    def service_uuid(self):
        pass
    def uuid(self):
        return self.uuid


class Test_DataDecoderTests(unittest.IsolatedAsyncioTestCase):

    ENGINE_RPM_UUID = "00000102-0000-1000-8000-ec55f9f5b963"
    COOLANT_TEMPERATURE_UUID = "00000103-0000-1000-8000-ec55f9f5b963"
    BATTERY_VOLTAGE_UUID = "00000104-0000-1000-8000-ec55f9f5b963"
    UNK_105_UUID = "00000105-0000-1000-8000-ec55f9f5b963"
    ENGINE_RUNTIME_UUID = "00000106-0000-1000-8000-ec55f9f5b963"
    CURRENT_FUEL_FLOW_UUID = "00000107-0000-1000-8000-ec55f9f5b963"
    UNK_108_UUID = "00000108-0000-1000-8000-ec55f9f5b963"
    UNK_109_UUID = "00000109-0000-1000-8000-ec55f9f5b963"
    OIL_PRESSURE_UUID = "0000010a-0000-1000-8000-ec55f9f5b963"
    UNK_10B_UUID = "0000010b-0000-1000-8000-ec55f9f5b963"
    UNK_10C_UUID = "0000010c-0000-1000-8000-ec55f9f5b963"
    UNK_10D_UUID = "0000010d-0000-1000-8000-ec55f9f5b963"   


    def configure_parameters(self, decoder:BleDeviceConnection):
        decoder.engine_parameters[1] = EngineParameter(EngineParameterType.ENGINE_RPM.value, 1)
        decoder.engine_parameters[210] = EngineParameter(EngineParameterType.COOLANT_TEMPERATURE.value, 210)
        decoder.engine_parameters[232] = EngineParameter(EngineParameterType.BATTERY_VOLTAGE.value, 232)
        decoder.engine_parameters[150] = EngineParameter(EngineParameterType.ENGINE_RUNTIME.value, 150)
        decoder.engine_parameters[10] = EngineParameter(EngineParameterType.CURRENT_FUEL_FLOW.value, 10)
        decoder.engine_parameters[181] = EngineParameter(EngineParameterType.OIL_PRESSURE.value, 181)

    async def test_notifications(self):

        config = BleConnectionConfig()
        config.device_name = "UnitTestRunner"

        decoder = BleDeviceConnection(config, None)
        self.configure_parameters(decoder)
        
        # Engine RPM
        await self.run_char_validation(decoder, 
                                       Test_DataDecoderTests.ENGINE_RPM_UUID,  
                                       bytes([0x01, 0x00, 0x5e, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
                                       606)
                
        await self.run_char_validation(decoder,
                                       Test_DataDecoderTests.ENGINE_RPM_UUID,
                                       bytes([0x01, 0x00, 0x7e, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
                                       4222)

        # Coolant Temperature
        await self.run_char_validation(decoder, 
                                       Test_DataDecoderTests.COOLANT_TEMPERATURE_UUID,  
                                       bytes([0xd2, 0x00, 0x40, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
                                       64)

        # Battery Voltage
        await self.run_char_validation(decoder,
                                       Test_DataDecoderTests.BATTERY_VOLTAGE_UUID,
                                       bytes([0xe8, 0x00, 0x8f, 0x2f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
                                       12175)

        # Engine Runtime
        await self.run_char_validation(decoder,
                                       Test_DataDecoderTests.ENGINE_RUNTIME_UUID,
                                       bytes([0x96, 0x00, 0xab, 0x16, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
                                       5803)

        # Fuel Flow
        await self.run_char_validation(decoder,
                                       Test_DataDecoderTests.CURRENT_FUEL_FLOW_UUID,
                                       bytes([0x0A, 0x00, 0x56, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
                                       598)
        
        await self.run_char_validation(decoder,
                                       Test_DataDecoderTests.CURRENT_FUEL_FLOW_UUID,
                                       bytes([0x0a, 0x00, 0xb5, 0x18, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
                                       6325)

        # Oil Pressure
        await self.run_char_validation(decoder,
                                       Test_DataDecoderTests.OIL_PRESSURE_UUID,
                                       bytes([0xB5, 0x00, 0xAE, 0x6B, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]),
                                       27566)


    async def run_char_validation(self, decoder: BleDeviceConnection, uuid: str, data, expected_result):
        char = BasicGATTCharacteristic(uuid, None, None)        
        promise = decoder.future_data_for_uuid(uuid)
        decoder.notification_handler(char, data)
        try:
            async with asyncio.timeout(1):
                result = await promise
                assert result == expected_result
        except TimeoutError:
            print("TimeoutError")
            pass


class Test_Conversions(unittest.TestCase):

    def test_hertz(self):
        assert Conversion.rpm_to_hertz(60) == 1
        assert Conversion.rpm_to_hertz(600) == 10
        assert Conversion.rpm_to_hertz(900) == 15
    
    def test_kelvin(self):
        assert Conversion.celsius_to_kelvin(0) == 273.15
        assert Conversion.celsius_to_kelvin(100) == 373.15

    def test_cubic_meters(self):

        data_value = 6325      # centiliters per hour
        liters_per_hour = data_value / 100.0
        gallons_per_hour = liters_per_hour * 0.2642  # gallons per liter
        cubic_meters_per_second = gallons_per_hour / 951019.38844

        Test_Conversions.compare_floats(Conversion.centiliters_to_cubic_meters(data_value), cubic_meters_per_second, 4)


    def test_pascals(self):
        data_value = 27510
        pascals = 275100
        assert Conversion.decapascals_to_pascals(data_value) == pascals

        psi_value = 40.0
        data_value = psi_value * 689.476
        Test_Conversions.compare_floats(Conversion.decapascals_to_pascals(data_value), 275790.4, 5)


    def test_volts(self):
        data_value = 1240
        assert Conversion.millivolts_to_volts(data_value), 12.40


    def round_to_sigfigs(value, sigfigs):
        if value == 0:
            return 0
        else:
            return round(value, sigfigs - int(math.floor(math.log10(abs(value)))) - 1)

    
    def compare_floats(a, b, sigfigs):
        a_rounded = Test_Conversions.round_to_sigfigs(a, sigfigs)
        b_rounded = Test_Conversions.round_to_sigfigs(b, sigfigs)
        logger.debug(f"{a_rounded} == {b_rounded}")
        assert a_rounded == b_rounded

if __name__ == "__main__":
    logging.basicConfig(stream = sys.stderr )
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
