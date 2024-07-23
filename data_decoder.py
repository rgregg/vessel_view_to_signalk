import argparse
import asyncio
import logging

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_16, uuid16_dict

logger = logging.getLogger(__name__)

class UUIDs:
    uuid16_lookup = {v: normalize_uuid_16(k) for k, v in uuid16_dict.items()}

    """Standard UUIDs from BLE protocol"""
    SYSTEM_ID_UUID = uuid16_lookup["System ID"]
    MODEL_NBR_UUID = uuid16_lookup["Model Number String"]
    DEVICE_NAME_UUID = uuid16_lookup["Device Name"]
    FIRMWARE_REV_UUID = uuid16_lookup["Firmware Revision String"]
    HARDWARE_REV_UUID = uuid16_lookup["Hardware Revision String"]
    SOFTWARE_REV_UUID = uuid16_lookup["Software Revision String"]
    MANUFACTURER_NAME_UUID = uuid16_lookup["Manufacturer Name String"]

    """Manufacturer specific UUIDs"""
    DEVICE_STARTUP_UUID = "00000300-0000-1000-8000-ec55f9f5b963"
    DEVICE_CONFIG_UUID = "00000001-0000-1000-8000-ec55f9f5b963"
    DEVICE_NEXT_UUID = "00000111-0000-1000-8000-ec55f9f5b963"
    DEVICE_201_UUID = "00000201-0000-1000-8000-ec55f9f5b963"

    """Engine data parameters"""
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

class Conversion:
    def convert_RPM_to_Hz(rpm):
        return rpm / 60.0

    def convert_Celsius_to_Kelvin(celsius):
        return celsius + 273.15

    def convert_Minutes_to_Seconds(minutes):
        return minutes * 60.0

    def convert_Liters_to_CubicMeters(value):
        liters_per_hour = value * 100.0
        cubic_meters_per_hour = liters_per_hour * 0.001
        cubic_meters_per_second = cubic_meters_per_hour / 3600
        return cubic_meters_per_second

    def convert_ToPascals(value):
        return value / 10.0
    
    def convert_ToVolts(value):
        return value / 1000.0

class VesselViewMobileReceiver:

    engine_id = "0"
    signalk_root_path = "propulsion"
    signalk_parameter_map = {
            UUIDs.ENGINE_RPM_UUID: { "path": "revolutions", "convert": Conversion.convert_RPM_to_Hz },
            UUIDs.COOLANT_TEMPERATURE_UUID: { "path": "temperature", "convert": Conversion.convert_Celsius_to_Kelvin  },
            UUIDs.BATTERY_VOLTAGE_UUID: { "path": "alternatorVoltage", "convert": Conversion.convert_ToVolts },
            UUIDs.ENGINE_RUNTIME_UUID: { "path": "runTime", "convert": Conversion.convert_Minutes_to_Seconds },
            UUIDs.CURRENT_FUEL_FLOW_UUID: {"path": "fuel.rate", "convert": Conversion.convert_Liters_to_CubicMeters},
            UUIDs.OIL_PRESSURE_UUID: { "path": "oilPressure", "convert": Conversion.convert_ToPascals },
            UUIDs.UNK_105_UUID: {},
            UUIDs.UNK_108_UUID: {},
            UUIDs.UNK_109_UUID: {},
            UUIDs.UNK_10B_UUID: {},
            UUIDs.UNK_10C_UUID: {},
            UUIDs.UNK_10D_UUID: {},
            UUIDs.DEVICE_201_UUID: {}
        }
    notification_futures_queue = { }

    def __init__(self):
        logger.debug("Created a new instance of decoder class")        

    async def run(self, args: argparse.Namespace):
        loop = asyncio.get_event_loop()

        logger.info("starting scan...")
        device = await BleakScanner.find_device_by_address(
            args.address, cb=dict(use_bdaddr=args.macos_use_bdaddr)
        )
        if device is None:
            logger.error("could not find device with address '%s'", args.address)
            return
        
        logger.info("connecting to device...")
        async with BleakClient(device) as client:
            logger.info("connected to device!")

            logger.debug("retriving BLE standard metadata")
            await self.retrieve_device_info(client)
            
            logger.debug("retriving VVM specific device information")
            await self.initalize_vvm(client)
            
            logger.debug("configuring data streaming notifications")
            await self.setup_data_notifications(client)

            logger.debug("enabling streaming")
            await self.set_streaming_mode(client, enabled=True)

            # run until the device is disconnected or
            # the operation is terminated
            logger.debug("running event loop forever")
            loop.run_forever()

    """
    Enable BLE notifications for the charateristics that we're interested in
    """
    async def setup_data_notifications(self, client: BleakClient):
        logger.debug("enabling notifications on data chars")

        for uuid in self.signalk_parameter_map:
            logger.debug("enabling notification on %s", uuid)
            await client.start_notify(uuid, self.notification_handler)

    """
    Handles BLE notifications and indications
    """
    def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        #Simple notification handler which prints the data received
        uuid = characteristic.uuid
        logger.info("Received notification from BLE - UUID: %s", uuid)

        # If the notification is about an engine property, we need to push
        # that information into the SignalK client as a property delta
        if uuid in self.signalk_parameter_map:
            options = self.signalk_parameter_map[uuid]
            
            # decode data from byte array to underlying value
            value = self.parse_data_from_device(data)
            self.trigger_event_listener(uuid, value)


            if "convert" in options:
                convert = options["convert"]
                new_value = convert(value)
                logger.debug("Converted value from %s to %s", value, new_value)
            else:
                new_value = value
                logger.debug("No data conversion: %s", value)

            if "path" in options:        
                path = self.signalk_root_path + "." + self.engine_id + "." + options["path"]
                logger.debug("Publishing value to SignalK %s", new_value)
                self.publish_to_signalk(path, new_value)

        else:
            logger.debug("Triggering notification for %s with data %s", uuid, data)
            self.trigger_event_listener(uuid, data)

    """
    Parses the byte stream from a device notification, strips
    the header bytes and converts the value to an integer with 
    little endian byte order
    """
    def parse_data_from_device(self, data):
        logger.debug("Recieved data from device: %s" ,data)
        data = data[2:]  # remove the header bytes
        value = int.from_bytes(data, byteorder='little')
        logger.debug("Converted to value: %s", value)
        return value

    """
    Submits the latest information received from the device to the SignalK
    websocket
    """
    def publish_to_signalk(self, path, data):
        # do something with the data and signalk 
        logger.info("Publishing delta to path: '%s', value '%s'", path, data)
        return

    """
    Sets up the VVM based on the patters from the mobile application. This is likely
    unnecessary and is just being used to receive data from the device but we need
    more signal to know for sure.
    """
    async def initalize_vvm(self, client: BleakClient):
        logger.debug("initalizing VVM device...")

        # read 0300 as byte array
        data1 = await client.read_gatt_char(UUIDs.DEVICE_STARTUP_UUID)

        # enable indiciations on 001
        await client.start_notify(UUIDs.DEVICE_CONFIG_UUID, self.notification_handler)
        await self.set_streaming_mode(client, enabled=False)
        await self.request_device_config()

        data = bytes([0x10, 0x27, 0x0])
        result = self.request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        logger.info("Response from 0111: %s", result)
        # expected result = 00102701010001

        data = bytes([0xCA, 0x0F, 0x0])
        result = self.request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        logger.info("Response from 0111: %s", result)
        # expected result = 00ca0f01010000

        data = bytes([0xC8, 0x0F, 0x0])
        result = self.request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        logger.info("Response from 0111: %s", result)
        # expected result = 00c80f01040000000000

    """
    Enable or disable engine data streaming via characteristic notifications
    """
    async def set_streaming_mode(client: BleakClient, enabled: bool):    
        if enabled:
            data = bytes([0xD, 0x1])
        else:
            data = bytes([0xD, 0x0])

        await client.write_gatt_char(UUIDs.DEVICE_CONFIG_UUID, data, response=True)

    """
    Writes the request to send the base state configuration from the device
    via indications on characteristic DEVICE_CONFIG_UUID. This data is returned
    over a series of indications on the DEVICE_CONFIG_UUID charateristic.
    """
    async def request_device_config(self, client: BleakClient):
        # Requests the initial data dump from 001
        data = bytes([0x28, 0x00, 0x03, 0x01])
        response = await self.request_configuration_data(client, UUIDs.DEVICE_CONFIG_UUID, data)

        # Response comes in a series of indications - we need to special case this.

        logger.info("Device Configuration Response: %s", response)

    """
    Writes data to the charateristic and waits for a notification that the
    charateristic data has updated before returning.
    """
    async def request_configuration_data(self, client: BleakClient, uuid: str, data: bytes):
        
        # add an event lisener to the queue
        logger.debug("writing data to char %s with value %s", uuid, data)
        future_data = self.add_event_listener(uuid)
        await client.write_gatt_char(uuid, data, response=True)

        # wait for an indication to arrive on the UUID specified, and then
        # return that data to the caller here.
        result = await future_data
        logger.debug("received future data %s on %s", result, uuid)
        return result

    """
    Add a new Future that returns data received from a notification / indication
    """
    def add_event_listener(self, uuid: str):
        # TODO: Do we need to add locking around this queue?

        events = []
        if uuid in self.notification_futures_queue:
            events = self.notification_futures_queue[uuid]
        else:
            self.notification_futures_queue[uuid] = events
        
        event = asyncio.Future()
        events.append(event)
        
        return event

    """
    Trigger the waiting Futures when data is received
    """
    def trigger_event_listener(self, uuid: str, data: bytes):
        # TODO: Do we need to add locking around this queue?
        if (uuid not in self.notification_futures_queue):
            futures = []
        else:
            futures = self.notification_futures_queue[uuid]
            del self.notification_futures_queue[uuid]

        for future in futures:
            future.set_result(data)
        

    """
    Retrieves the BLE standard data for the device
    """
    async def retrieve_device_info(self, client: BleakClient):
        system_id = await client.read_gatt_char(UUIDs.SYSTEM_ID_UUID)
        logger.info(
            "System ID: {0}".format(
                ":".join(["{:02x}".format(x) for x in system_id[::-1]])
            )
        )

        model_number = await client.read_gatt_char(UUIDs.MODEL_NBR_UUID)
        logger.info("Model Number: {0}".format("".join(map(chr, model_number))))
        
        try:
            device_name = await client.read_gatt_char(UUIDs.DEVICE_NAME_UUID)
            print("Device Name: {0}".format("".join(map(chr, device_name))))
        except Exception:
            pass

        manufacturer_name = await client.read_gatt_char(UUIDs.MANUFACTURER_NAME_UUID)
        logger.info("Manufacturer Name: {0}".format("".join(map(chr, manufacturer_name))))

        firmware_revision = await client.read_gatt_char(UUIDs.FIRMWARE_REV_UUID)
        logger.info("Firmware Revision: {0}".format("".join(map(chr, firmware_revision))))

        hardware_revision = await client.read_gatt_char(UUIDs.HARDWARE_REV_UUID)
        logger.info("Hardware Revision: {0}".format("".join(map(chr, hardware_revision))))

        software_revision = await client.read_gatt_char(UUIDs.SOFTWARE_REV_UUID)
        logger.info("Software Revision: {0}".format("".join(map(chr, software_revision))))

        services = await client.services
        logger.info("Services: {0}".format("".join(map(chr, services))))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    # device_group = parser.add_mutually_exclusive_group(required=True)

    # device_group.add_argument(
    #     "--name",
    #     metavar="<name>",
    #     help="the name of the bluetooth device to connect to",
    # )
    parser.add_argument(
        "--address",
        metavar="<address>",
        help="the address of the bluetooth device to connect to",
        required=True
    )

    parser.add_argument(
        "--macos-use-bdaddr",
        action="store_true",
        help="when true use Bluetooth address instead of UUID on macOS",
    )

    parser.add_argument(
        "--signalk-ws",
        action="store_true",
        help="The URL for the signalk websocket service.",
        default="ws://localhost:3000/signalk/v1/stream?subscribe=none",
    )
    
    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="sets the log level to debug",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)-15s %(name)-8s %(levelname)s: %(message)s",
    )

    client = VesselViewMobileReceiver()
    asyncio.run(client.run(args))