from data_decoder import UUIDs, VesselViewMobileReceiver
import logging

logger = logging.getLogger(__name__)


class DataDecoderTests:

    def test_notifications():
        decoder = VesselViewMobileReceiver()
        decoder.engine_id = "0"
        
        char = {
            "uuid": UUIDs.ENGINE_RPM_UUID
         }
        data = bytes([0x01, 0x00, 0x5e, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])

        decoder.notification_handler(char, data)
        return


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)-15s %(name)-8s %(levelname)s: %(message)s",
    )

    tests = DataDecoderTests()
    
    tests.test_notifications()


