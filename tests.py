from data_decoder import UUIDs, VesselViewMobileReceiver
import logging
from bleak import BleakGATTCharacteristic

logger = logging.getLogger(__name__)


class TestCharacteristic(BleakGATTCharacteristic):
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


class DataDecoderTests:

    def test_notifications(self):
        decoder = VesselViewMobileReceiver()
        decoder.engine_id = "0"
        
        # Engine RPM
        char = TestCharacteristic(UUIDs.ENGINE_RPM_UUID, None, None)
        data = bytes([0x01, 0x00, 0x5e, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        decoder.notification_handler(char, data)

        # Coolant Temperature
        char = TestCharacteristic(UUIDs.COOLANT_TEMPERATURE_UUID, None, None)        
        data = bytes([0xd2, 0x00, 0x40, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        decoder.notification_handler(char, data)

        # Battery Voltage
        char = TestCharacteristic(UUIDs.BATTERY_VOLTAGE_UUID, None, None)        
        data = bytes([0xe8, 0x00, 0x8f, 0x2f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        decoder.notification_handler(char, data)

        # Engine Runtime
        char = TestCharacteristic(UUIDs.ENGINE_RUNTIME_UUID, None, None)        
        data = bytes([0x96, 0x00, 0xab, 0x16, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        decoder.notification_handler(char, data)

        # Fuel Flow
        char = TestCharacteristic(UUIDs.CURRENT_FUEL_FLOW_UUID, None, None)        
        data = bytes([0x0A, 0x00, 0x56, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        decoder.notification_handler(char, data)

        # Oil Pressure
        char = TestCharacteristic(UUIDs.OIL_PRESSURE_UUID, None, None)        
        data = bytes([0xB5, 0x00, 0xAE, 0x6B, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        decoder.notification_handler(char, data)


        return


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)-15s %(name)-8s %(levelname)s: %(message)s",
    )

    tests = DataDecoderTests()
    
    tests.test_notifications()


