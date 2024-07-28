import argparse
import asyncio
import logging

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_16, uuid16_dict
from bleak.exc import BleakCharacteristicNotFoundError

from data_logger import CSVLogger
from signalk_publisher import SignalKPublisher

logger = logging.getLogger(__name__)

class VesselViewMobileReceiver:

    rescan_timeout_seconds = 10

    def __init__(self, device_address, publish_delta_func):
        logger.debug("Created a new instance of decoder class")
        self.device_address = device_address
        self.device = None
        self.abort = False
        self.engine_id = "0"
        self.signalk_root_path = "propulsion"
        self.signalk_parameter_map = {
            UUIDs.ENGINE_RPM_UUID: { "path": "revolutions", "convert": Conversion.to_hertz },
            UUIDs.COOLANT_TEMPERATURE_UUID: { "path": "temperature", "convert": Conversion.to_kelvin  },
            UUIDs.BATTERY_VOLTAGE_UUID: { "path": "alternatorVoltage", "convert": Conversion.to_volts },
            UUIDs.ENGINE_RUNTIME_UUID: { "path": "runTime", "convert": Conversion.to_seconds },
            UUIDs.CURRENT_FUEL_FLOW_UUID: {"path": "fuel.rate", "convert": Conversion.to_cubic_meters},
            UUIDs.OIL_PRESSURE_UUID: { "path": "oilPressure", "convert": Conversion.to_pascals },
            UUIDs.UNK_105_UUID: {},
            UUIDs.UNK_108_UUID: {},
            UUIDs.UNK_109_UUID: {},
            UUIDs.UNK_10B_UUID: {},
            UUIDs.UNK_10C_UUID: {},
            UUIDs.UNK_10D_UUID: {},
            UUIDs.DEVICE_201_UUID: {}
        }
        self.notification_futures_queue = { }
        self.cancel_signal = asyncio.Future()
        self.rescan_signal = asyncio.Future()
        self.publish_delta_func = publish_delta_func
        self.last_values = {}

        fieldnames = ["timestamp",
                     UUIDs.ENGINE_RPM_UUID,
                     UUIDs.COOLANT_TEMPERATURE_UUID,
                     UUIDs.BATTERY_VOLTAGE_UUID, 
                     UUIDs.ENGINE_RUNTIME_UUID,
                     UUIDs.CURRENT_FUEL_FLOW_UUID,
                     UUIDs.OIL_PRESSURE_UUID,
                     UUIDs.UNK_105_UUID,
                     UUIDs.UNK_108_UUID,
                     UUIDs.UNK_109_UUID,
                     UUIDs.UNK_10B_UUID,
                     UUIDs.UNK_10C_UUID,
                     UUIDs.UNK_10D_UUID,
                     ]
        self.csv_logger = CSVLogger("data.csv", fieldnames)

    """
    Triggers scanning for the BLE hardware device if there is no connection to the device currently available. This can be
    used as an external trigger based on some other indication (e.g. ignition switch, GPS movement, etc.)
    """
    def scan_for_device(self):
        signal = self.rescan_signal
        self.rescan_signal = asyncio.Future()
        signal.done()

    """
    Main run loop for detecting the BLE device and processing data from it
    """
    async def run(self, task_group):
        loop = asyncio.get_event_loop()
        
        while not self.abort:

            # Loop on device discovery
            while self.device is None:
                logger.info("Scanning for bluetooth device...")
                found_device = await BleakScanner.find_device_by_address(self.device_address)
                
                if found_device is None:
                    logger.warn("Could not find BLE device with address '%s'. Will continue to scan...", self.device_address)
                    # Wait for the timeout or the future to be triggered
                    try:
                        await asyncio.wait_for(asyncio.shield(self.rescan_signal), timeout=self.rescan_timeout_seconds)
                    except TimeoutError:
                        logger.debug("Timeout has elapsed on device scan, starting to scan again.")

                else:
                    self.device = found_device

                if self.abort:
                    logger.debug("Aborting BLE connection and exiting loop")
                    return


            # Run until the device is disconnected or the process is cancelled
            logger.info(f"Found BLE device {self.device} ")
            async with BleakClient( self.device
#                                    disconnected_callback=self.device_disconnected()
                                    ) as client:
                logger.debug("Connected.")

                logger.debug("Retriving device identification metadata...")
                await self.retrieve_device_info(client)
                
                logger.debug("Initalizing VVM...")
                await self.initalize_vvm(client)
                
                logger.debug("Configuring data streaming notifications...")
                await self.setup_data_notifications(client)

                logger.info("Enabling data streaming from BLE device")
                await self.set_streaming_mode(client, enabled=True)

                # run until the device is disconnected or
                # the operation is terminated
                self.cancel_signal = asyncio.Future()
                await self.cancel_signal
            
            self.device = None
        #end of self.abort loop


        def device_disconnected(self):
            # handle the device disconnecting from the system
            logger.warn("BLE device was disconnected. Will attempt to reconnect.")
            self.abort = False
            self.cancel_signal.done()


    """
    Disconnect from the BLE device and clean up anything we were doing to close down the loop
    """
    async def close(self):
        logger.info("Disconnecting from bluetooth device...")
        self.abort = True
        self.rescan_signal.done()  # cancels the wait for a new device
        self.cancel_signal.done()  # cancels the loop if we have a device and disconnects
        logger.debug("completed close operations")

    """
    Enable BLE notifications for the charateristics that we're interested in
    """
    async def setup_data_notifications(self, client: BleakClient):
        logger.debug("enabling notifications on data chars")

        for uuid in self.signalk_parameter_map:
            logger.debug("enabling notification on %s", uuid)
            await client.start_notify(uuid, self.notification_handler)

        self.last_values = {}

    """
    Handles BLE notifications and indications
    """
    def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        #Simple notification handler which prints the data received
        uuid = characteristic.uuid
        logger.debug(f"Received notification from BLE - UUID: {uuid}; data: {data.hex()}")

        # If the notification is about an engine property, we need to push
        # that information into the SignalK client as a property delta
        if uuid in self.signalk_parameter_map:
            options = self.signalk_parameter_map[uuid]
            
            # decode data from byte array to underlying value
            value = self.parse_data_from_device(data)
            self.trigger_event_listener(uuid, value)
            self.csv_logger.update_property(uuid, value)

            if "convert" in options:
                convert = options["convert"]
                new_value = convert(value)
                logger.debug("Converted value from %s to %s", value, new_value)
            else:
                new_value = value
                logger.debug("No data conversion: %s", value)

            if "path" in options:        
                path = self.signalk_root_path + "." + self.engine_id + "." + options["path"]
                logger.debug(f"Publishing value {new_value} to path '{path}'")
                self.publish_to_signalk(path, new_value)
            else:
                logger.debug(f"No path found for uuid: {uuid}")
            
            self.last_values[uuid] = new_value
            
        else:
            logger.debug("Triggering notification for %s with data %s", uuid, data)
            self.trigger_event_listener(uuid, data)

    def dump_last_values(self):
        logger.info(','.join(self.last_values.values()))        


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
    def publish_to_signalk(self, path, value):
        logger.debug("Publishing delta to path: '%s', value '%s'", path, value)
        if self.publish_delta_func is not None:
            loop = asyncio.get_event_loop()
            loop.create_task(self.publish_delta_func(path, value))
        else:
            logging.info("Cannot publish to signalk")

    """
    Sets up the VVM based on the patters from the mobile application. This is likely
    unnecessary and is just being used to receive data from the device but we need
    more signal to know for sure.
    """
    async def initalize_vvm(self, client: BleakClient):
        logger.debug("initalizing VVM device...")

        # read 0300 as byte array
        data1 = await self.read_char(client, UUIDs.DEVICE_STARTUP_UUID)
        logger.info("Initial configuration read %s", data1)

        # enable indiciations on 001
        await self.set_streaming_mode(client, enabled=False)
        config = await self.request_device_config(client)

        data = bytes([0x10, 0x27, 0x0])
        result = await self.request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        logger.info("Response from 111: %s, expected: 00102701010001", result.hex())
        # expected result = 00102701010001

        data = bytes([0xCA, 0x0F, 0x0])
        result = await self.request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        logger.info("Response from 0111: %s, expected: 00ca0f01010000", result.hex())
        # expected result = 00ca0f01010000

        data = bytes([0xC8, 0x0F, 0x0])
        result = await self.request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        logger.info("Response from 0111: %s, expected: 00c80f01040000000000", result.hex())
        # expected result = 00c80f01040000000000

    """
    Enable or disable engine data streaming via characteristic notifications
    """
    async def set_streaming_mode(self, client: BleakClient, enabled):
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
        
        logger.info("Requesting device configuration data")
        await client.start_notify(UUIDs.DEVICE_CONFIG_UUID, self.notification_handler)
        
        # Requests the initial data dump from 001
        data = bytes([0x28, 0x00, 0x03, 0x01])
        
        uuid = UUIDs.DEVICE_CONFIG_UUID
        keys = [0,1,2,3,4,5,6,7,8,9]        # data is returned as a series of 10 updates to the UUID
        
        future_data = [self.data_for_uuid(uuid, key) for key in keys]

        try:
            async with asyncio.timeout(10):
                await client.write_gatt_char(uuid, data, response=True)
                result_data = await asyncio.gather(*future_data)

                result_hex = [ d.hex()  for d in result_data]
                result = '\n'.join(result_hex)

                logger.info(f"Device Configuration Response: {result}")
                return result
        except TimeoutError:
            logger.debug("timeout waiting for configuration data to return")
            return None
       

    """
    Writes data to the charateristic and waits for a notification that the
    charateristic data has updated before returning.
    """
    async def request_configuration_data(self, client: BleakClient, uuid: str, data: bytes):
        
        await client.start_notify(uuid, self.notification_handler)

        # add an event lisener to the queue
        logger.debug("writing data to char %s with value %s", uuid, data.hex())

        future_data_result = self.data_for_uuid(uuid)
        await client.write_gatt_char(uuid, data, response=True)
        
        # wait for an indication to arrive on the UUID specified, and then
        # return that data to the caller here.

        try:
            async with asyncio.timeout(5):
                result = await future_data_result
                logger.debug("received future data %s on %s", result.hex(), uuid)
                return result
        except TimeoutError:
            logger.debug("timeout waiting for configuration data to return")
        finally:
            await client.stop_notify(uuid)


    """
    Generate a promise for the data that will be received in the future for a given characteristic
    """
    def data_for_uuid(self, uuid: str, key = None):
        
        logger.debug("future promise for data on uuid: %s, key: %s", uuid, key)

        id = uuid
        if key is not None:
            id = f"{uuid}+{key}"

        logger.debug("future promise id: %s", id)        
        if id in self.notification_futures_queue:
            logger.debug("key already has a promise waiting")
            return self.notification_futures_queue[id]

        logger.debug("key is a new promise")
        # create a new future and save it for later
        future = asyncio.Future()
        self.notification_futures_queue[id] = future
        return future


    """
    Trigger the waiting Futures when data is received
    """
    def trigger_event_listener(self, uuid: str, data: bytes):
        
        logger.debug(f"triggering event listener for {uuid} with data: {data}")

        if uuid in self.notification_futures_queue:
            future = self.notification_futures_queue[uuid]
            del self.notification_futures_queue[uuid]
            future.set_result(data)

        # handle promises for data based on the uuid + first byte of the response
        try:
            key = int(data[0])
            id = f"{uuid}+{key}"
            logger.debug(f"checking for notification handler on key: {key}, id: {id}")
            if id in self.notification_futures_queue:
                future = self.notification_futures_queue[id]
                del self.notification_futures_queue[id]
                future.set_result(data)
        except TypeError:
            return
        except IndexError:
            return

    """
    Read data from the BLE device with consistent error handling
    """
    async def read_char(self, client: BleakClient, uuid: str):
        if not client.is_connected:
            logger.warn("BLE device is not connected while trying to read data.")
            return None
    
        try:
            result = await client.read_gatt_char(uuid)
            return result
        except BleakCharacteristicNotFoundError:
            logger.warn("BLE device did not have the requested data: %s", uuid)
            return None
            


    """
    Retrieves the BLE standard data for the device
    """
    async def retrieve_device_info(self, client: BleakClient):
#        system_id = await self.read_char(client, UUIDs.SYSTEM_ID_UUID)
#	if system_id is not None:
#           logger.info(
#               "System ID: {0}".format(
#                   ":".join(["{:02x}".format(x) for x in system_id[::-1]])
#               )
#           )

        model_number = await self.read_char(client, UUIDs.MODEL_NBR_UUID)
        logger.info("Model Number: {0}".format("".join(map(chr, model_number))))
        
        device_name = await self.read_char(client, UUIDs.DEVICE_NAME_UUID)
        logger.info("Device Name: {0}".format("".join(map(chr, device_name))))

        manufacturer_name = await self.read_char(client, UUIDs.MANUFACTURER_NAME_UUID)
        logger.info("Manufacturer Name: {0}".format("".join(map(chr, manufacturer_name))))

        firmware_revision = await self.read_char(client, UUIDs.FIRMWARE_REV_UUID)
        logger.info("Firmware Revision: {0}".format("".join(map(chr, firmware_revision))))

#        hardware_revision = await self.read_char(client, UUIDs.HARDWARE_REV_UUID)
#        logger.info("Hardware Revision: {0}".format("".join(map(chr, hardware_revision))))

#        software_revision = await self.read_char(client, UUIDs.SOFTWARE_REV_UUID)
#        logger.info("Software Revision: {0}".format("".join(map(chr, software_revision))))


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
    def to_hertz(rpm):
        return rpm / 60.0

    def to_kelvin(celsius):
        return celsius + 273.15

    def to_seconds(minutes):
        return minutes * 60

    def to_cubic_meters(value):
        liters_per_hour = value * 10000
        cubic_meters_per_hour = liters_per_hour * 0.001
        cubic_meters_per_second = cubic_meters_per_hour / 3600
        return cubic_meters_per_second

    def to_pascals(value):
        return value * 10
    
    def to_volts(value):
        return value / 1000.0
