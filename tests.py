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
        
        # Engine RPM (conversion)
        char = TestCharacteristic(UUIDs.ENGINE_RPM_UUID, None, None)
        data = bytes([0x01, 0x00, 0x5e, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        decoder.notification_handler(char, data)

        # Battery Voltage (no conversion)
        char = TestCharacteristic(UUIDs.BATTERY_VOLTAGE_UUID, None, None)        
        data = bytes([0xe8, 0x00, 0x8f, 0x2f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
        decoder.notification_handler(char, data)


        return


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)-15s %(name)-8s %(levelname)s: %(message)s",
    )

    tests = DataDecoderTests()
    
    tests.test_notifications()


