"""BLE connection module"""

import asyncio
import logging

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_16, uuid16_dict
from bleak.exc import BleakCharacteristicNotFoundError

from .csv_writer import CSVWriter
from .futures_queue import FuturesQueue
from .config_decoder import EngineParameter, ConfigDecoder, EngineParameterType

logger = logging.getLogger(__name__)

class BleDeviceConnection:
    """Handles the connection to the BLE hardware device"""

    rescan_timeout_seconds = 10

    def __init__(self, config: 'BleConnectionConfig', publish_delta_func, health_status):
        logger.debug("Created a new instance of decoder class")
        self.__config = config

        self.__device = None
        self.__abort = False
        self.__cancel_signal = asyncio.Future()
        self.__publish_delta_func = publish_delta_func
        self.__notification_queue = FuturesQueue()
        self.__engine_parameters = {}
        self.__csv_writer = None
        self.__task_group = None
        self.__health = health_status

    @property
    def device_address(self):
        """Returns the hardware address for the device to be located"""
        return self.__config.device_address
    
    @property
    def device_name(self):
        """Returns the device name for the device to be located"""
        return self.__config.device_name
    
    @property
    def retry_interval(self):
        """Interval in seconds for retrying when an error occurs"""
        return self.__config.retry_interval
    
    @property
    def engine_parameters(self):
        """Set of parameters detected from the hardware device"""
        return self.__engine_parameters
    
    @property
    def csv_writer(self):
        """Instance of a CSV output writer for data logging"""
        return self.__csv_writer
    
    @csv_writer.setter
    def csv_writer(self, value):
        self.__csv_writer = value
    
   
    def cb_disconnected(self):
        """ Handle when the BLE device disconnects """

        logger.info("BLE device has disconnected")
        self.__cancel_signal.done()


    async def run(self, task_group):
        """Main run loop for detecting the BLE device and processing data from it"""
        self.__task_group = task_group
        
        while not self.__abort:
            # Loop on device discovery
            while self.__device is None:
                await self.scan_for_device()
                if self.__abort:
                    self.set_health(False, "device discovery scan aborted")
                    return

            # Run until the device is disconnected or the process is cancelled
            logger.info("Found BLE device %s", self.__device)
            
            # configure the device and loop until abort or disconnect
            await self.device_init_and_loop()

            # reset our internal device to none since we are not connected
            self.__device = None

    def set_health(self, value: bool, message: str = None):
        """Sets the health of the BLE connection"""
        self.__health["bluetooth"] = value
        if message is None:
            del self.__health["bluetooth_error"]
        else:
            self.__health["bluetooth_error"] = message
            logger.warning(message)


    async def device_init_and_loop(self):
        """Initalize BLE device and loop receiving data"""
        try:
            async with BleakClient(self.__device,
                                    disconnected_callback=self.cb_disconnected
                                    ) as client:
                
                self.set_health(True, "Connected to device")

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
                self.__cancel_signal = asyncio.Future()
                await self.__cancel_signal
        except Exception as e:
            self.set_health(False, f"Device error: {e}")

    async def scan_for_device(self):
        """Scan for BLE device with matching info"""

        if self.device_address is not None:
            logger.info("Scanning for bluetooth device with ID: '%s'...", self.device_address)
        elif self.device_name is not None:
            logger.info("Scanning for bluetooth device with name: '%s'...", self.device_name)

        self.set_health(True, "Scanning for device")
                
        async with BleakScanner() as scanner:
            async for device_info in scanner.advertisement_data():
                device = device_info[0]
                logger.debug("Found BLE device: %s", device)
                if self.device_address is not None and device.address == self.device_address:
                    logger.info("Found matching device by address: %s", device)
                    self.__device = device
                    break
                if self.device_name is not None and device.name == self.device_name:
                    logger.info("Found matching device by name: %s", device)
                    self.__device = device
                    break

    def configure_csv_output(self, engine_params):
        """
        Configure the CSV output logger if enabled - with the engine parameters the connected
        device supports.
        """
        
        if self.__config.csv_output_enabled:
            fieldnames = [ "timestamp" ]
            for param in engine_params:
                if param.enabled:
                    fieldnames.append(param.signalk_path)

            self.csv_writer = CSVWriter(self.__config.csv_output_file, fieldnames)
        else:
            self.csv_writer = None

    async def close(self):
        """
        Disconnect from the BLE device and clean up anything we were doing to close down the loop
        """

        logger.info("Disconnecting from bluetooth device...")
        self.__abort = True
        self.__cancel_signal.done()  # cancels the loop if we have a device and disconnects
        logger.debug("completed close operations")
        self.set_health(False, "shutting down")

    async def setup_data_notifications(self, client: BleakClient):
        """
        Enable BLE notifications for the charateristics that we're interested in
        """

        logger.debug("enabling notifications on data chars")
        
        # Iterate over all characteristics in all services and subscribe
        for service in client.services:
            for characteristic in service.characteristics:
                if "notify" in characteristic.properties:
                    try:
                        await client.start_notify(characteristic.uuid, self.notification_handler)
                        logger.debug("Subscribed to %s", characteristic.uuid)
                    except Exception as e:
                        logger.warning("Unable to subscribe to  %s: %s", characteristic.uuid, e)
    

    def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """
        Handles BLE notifications and indications
        """

        #Simple notification handler which prints the data received
        uuid = characteristic.uuid
        logger.debug("Received notification from BLE - UUID: %s; data: %s", uuid, data.hex())

        # If the notification is about an engine property, we need to push
        # that information into the SignalK client as a property delta

        data_header = int.from_bytes(data[:2])
        logger.debug("data_header: %s", data_header)

        matching_param = self.__engine_parameters.get(data_header)
        logger.debug("Matching parameter: %s", matching_param)
        
        if matching_param:
            # decode data from byte array to underlying value (remove header bytes and convert to int)
            decoded_value = self.strip_header_and_convert_to_int(data)
            self.trigger_event_listener(uuid, decoded_value, False)
            self.convert_and_publish_data(matching_param, decoded_value)

            logger.info("Received data for %s with value %s", matching_param.signalk_path, decoded_value)
            try:
                if self.csv_writer is not None:
                    if self.__config.csv_output_raw:
                        self.csv_writer.update_property(matching_param.signalk_path, data.hex())
                    else:
                        self.csv_writer.update_property(matching_param.signalk_path, decoded_value)
            except Exception as e:
                logger.warning("Unable to write data to CSV: %s", e)
        else:
            logger.debug("Triggered default notification for UUID: %s with data %s", uuid, data.hex())
            self.trigger_event_listener(uuid, data, True)

    def convert_and_publish_data(self, engine_param: EngineParameter, decoded_value):
        """
        Converts data using the engine paramater conversion function into the signal k
        expected format and then publishes the data using the singalK API connector
        """

        path = engine_param.signalk_path
        convert_func = Conversion.conversion_for_parameter_type(engine_param.parameter_type)
        output_value = convert_func(decoded_value)
        if path:
            logger.debug("Publishing value '%s' to path '%s'", output_value, path)
            self.publish_to_signalk(path, output_value)
        else:
            logger.debug("No path found for parameter: '%s' with value '%s'", engine_param, output_value)


    def strip_header_and_convert_to_int(self, data):
        """
        Parses the byte stream from a device notification, strips
        the header bytes and converts the value to an integer with 
        little endian byte order
        """


        logger.debug("Recieved data from device: %s" ,data)
        data = data[2:]  # remove the header bytes
        value = int.from_bytes(data, byteorder='little')
        logger.debug("Converted to value: %s", value)
        return value

    def publish_to_signalk(self, path, value):
        """
        Submits the latest information received from the device to the SignalK
        websocket
        """

        logger.debug("Publishing delta to path: '%s', value '%s'", path, value)
        if self.__publish_delta_func is not None:
            loop = asyncio.get_event_loop()
            loop.create_task(self.__publish_delta_func(path, value))
        else:
            logger.info("Cannot publish to signalk")

    async def initalize_vvm(self, client: BleakClient):
        """
        Sets up the VVM based on the patters from the mobile application. This is likely
        unnecessary and is just being used to receive data from the device but we need
        more signal to know for sure.
        """

        logger.debug("initalizing VVM device...")

        # enable indiciations on 001
        await self.set_streaming_mode(client, enabled=False)
        

        # Indicates which parameters are available on the device
        engine_params = await self.request_device_parameter_config(client)
        self.update_engine_params(engine_params)

        data = bytes([0x10, 0x27, 0x0])
        result = await self.request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        logger.info("Response: %s, expected: 00102701010001", result.hex())
        # expected result = 00102701010001

        data = bytes([0xCA, 0x0F, 0x0])
        result = await self.request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        logger.info("Response: %s, expected: 00ca0f01010000", result.hex())
        # expected result = 00ca0f01010000

        data = bytes([0xC8, 0x0F, 0x0])
        result = await self.request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        logger.info("Response: %s, expected: 00c80f01040000000000", result.hex())
        # expected result = 00c80f01040000000000

    def update_engine_params(self, engine_params):
        """Update parameters with new values"""
        self.configure_csv_output(engine_params)
        self.__engine_parameters = { param.notification_header: param for param in engine_params }

    async def set_streaming_mode(self, client: BleakClient, enabled):
        """
        Enable or disable engine data streaming via characteristic notifications
        """

        if enabled:
            data = bytes([0xD, 0x1])
        else:
            data = bytes([0xD, 0x0])

        await client.write_gatt_char(UUIDs.DEVICE_CONFIG_UUID, data, response=True)

    async def request_device_parameter_config(self, client: BleakClient):
        """
        Writes the request to send the parameter conmfiguration from the device
        via indications on characteristic DEVICE_CONFIG_UUID. This data is returned
        over a series of indications on the DEVICE_CONFIG_UUID charateristic.
        """

        logger.info("Requesting device parameter configuration data")
        await client.start_notify(UUIDs.DEVICE_CONFIG_UUID, self.notification_handler)
        
        # Requests the initial data dump from 001
        data = bytes([0x28, 0x00, 0x03, 0x01])
        
        uuid = UUIDs.DEVICE_CONFIG_UUID
        keys = [0,1,2,3,4,5,6,7,8,9]        # data is returned as a series of 10 updates to the UUID
        
        future_data = [self.future_data_for_uuid(uuid, key) for key in keys]

        try:
            async with asyncio.timeout(10):
                await client.write_gatt_char(uuid, data, response=True)
                result_data = await asyncio.gather(*future_data)

                decoder = ConfigDecoder()
                decoder.add(result_data)
                engine_parameters = decoder.combine_and_parse_data()
                logger.info("Device parameters: %s", engine_parameters)
                return engine_parameters
            
        except TimeoutError:
            logger.debug("timeout waiting for configuration data to return")
            return None



    async def request_configuration_data(self, client: BleakClient, uuid: str, data: bytes):
        """
        Writes data to the charateristic and waits for a notification that the
        charateristic data has updated before returning.
        """

        await client.start_notify(uuid, self.notification_handler)

        # add an event lisener to the queue
        logger.debug("writing data to char %s with value %s", uuid, data.hex())

        future_data_result = self.future_data_for_uuid(uuid)
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


    def future_data_for_uuid(self, uuid: str, key = None):
        """
        Generate a promise for the data that will be received
        in the future for a given characteristic
        """

        logger.debug("future promise for data on uuid: %s, key: %s", uuid, key)
        key_id = uuid
        if key is not None:
            key_id = f"{uuid}+{key}"

        return self.__notification_queue.register(key_id)


    def trigger_event_listener(self, uuid: str, data, raw_bytes_from_device):
        """
        Trigger the waiting Futures when data is received
        """

        logger.debug("triggering event listener for %s with data: %s", uuid, data)
        self.__notification_queue.trigger(uuid, data)
        
        # handle promises for data based on the uuid + first byte of the response if raw data
        if raw_bytes_from_device:
            try:
                key_id = f"{uuid}+{int(data[0])}"
                logger.debug("triggering notification handler on id: %s", key_id)
                self.__notification_queue.trigger(key_id, data)
            except Exception as e:
                logger.warning("Exception triggering notification: %s", e)

    async def read_char(self, client: BleakClient, uuid: str):
        """
        Read data from the BLE device with consistent error handling
        """

        if not client.is_connected:
            logger.warning("BLE device is not connected while trying to read data.")
            return None
    
        try:
            result = await client.read_gatt_char(uuid)
            return result
        except BleakCharacteristicNotFoundError:
            logger.warning("BLE device did not have the requested data: %s", uuid)
            return None
            


    async def retrieve_device_info(self, client: BleakClient):
        """
        Retrieves the BLE standard data for the device
        """

        model_number = await self.read_char(client, UUIDs.MODEL_NBR_UUID)
        logger.info("Model Number: %s", "".join([chr(c) for c in model_number]))
        
        device_name = await self.read_char(client, UUIDs.DEVICE_NAME_UUID)
        logger.info("Device Name: %s", "".join([chr(c) for c in device_name]))

        manufacturer_name = await self.read_char(client, UUIDs.MANUFACTURER_NAME_UUID)
        logger.info("Manufacturer Name: %s", "".join([chr(c) for c in manufacturer_name]))

        firmware_revision = await self.read_char(client, UUIDs.FIRMWARE_REV_UUID)
        logger.info("Firmware Revision: %s", "".join([chr(c) for c in firmware_revision]))


class UUIDs:
    """Common UUIDs for this hardware """
    uuid16_lookup = {v: normalize_uuid_16(k) for k, v in uuid16_dict.items()}

    ## Standard UUIDs from BLE protocol
    MODEL_NBR_UUID = uuid16_lookup["Model Number String"]
    DEVICE_NAME_UUID = uuid16_lookup["Device Name"]
    FIRMWARE_REV_UUID = uuid16_lookup["Firmware Revision String"]
    MANUFACTURER_NAME_UUID = uuid16_lookup["Manufacturer Name String"]

    ## Manufacturer specific UUIDs
    DEVICE_STARTUP_UUID = "00000302-0000-1000-8000-ec55f9f5b963"
    DEVICE_CONFIG_UUID = "00000001-0000-1000-8000-ec55f9f5b963"
    DEVICE_NEXT_UUID = "00000111-0000-1000-8000-ec55f9f5b963"
    DEVICE_201_UUID = "00000201-0000-1000-8000-ec55f9f5b963"

class Conversion:
    """Static conversion methods from hardware parameters to SI units"""
    @staticmethod
    def rpm_to_hertz(rpm):
        """Convert from RPM to Hertz"""
        return rpm / 60.0
    
    @staticmethod
    def celsius_to_kelvin(celsius):
        """Convert from Celsius to Kelvin"""
        return celsius + 273.15
    
    @staticmethod
    def minutes_to_seconds(minutes):
        """Convert minutes to seconds"""
        return minutes * 60
    
    @staticmethod
    def centiliters_to_cubic_meters(cl_per_hour):
        """Convert centiliters to cubmic meters"""
        # Conversion factors
        m3_per_cl = 0.00001
        seconds_per_hour = 3600.0
        
        m3_per_second = cl_per_hour * m3_per_cl / seconds_per_hour
        return m3_per_second
    
    @staticmethod
    def decapascals_to_pascals(value):
        """Convert decapascals to pascals"""
        return value * 10
    
    @staticmethod
    def millivolts_to_volts(value):
        """Convert millivolts to volts"""
        return value / 1000.0
    
    @staticmethod
    def identity_function(value):
        """No conversion, return the input"""
        return value
    
    @staticmethod
    def conversion_for_parameter_type(param: EngineParameterType):
        """Provide the conversion function based on parameter type"""
        if param == EngineParameterType.BATTERY_VOLTAGE:
            return Conversion.millivolts_to_volts
        if param == EngineParameterType.COOLANT_TEMPERATURE:
            return Conversion.celsius_to_kelvin
        if param == EngineParameterType.CURRENT_FUEL_FLOW:
            return Conversion.centiliters_to_cubic_meters
        if param == EngineParameterType.ENGINE_RPM:
            return Conversion.rpm_to_hertz
        if param == EngineParameterType.ENGINE_RUNTIME:
            return Conversion.minutes_to_seconds
        if param == EngineParameterType.OIL_PRESSURE:
            return Conversion.decapascals_to_pascals
        
        logger.error("Unknown conversion for unknown datatype: %s", param)
        return Conversion.identity_function

class BleConnectionConfig:
    """Configuration information for the BLE connection"""
    def __init__(self):
        self.__device_address = None
        self.__device_name = None
        self.__retry_interval = 30
        self.__csv_output_enabled = True
        self.__csv_output_file = "./logs/data.csv"
        self.__csv_output_keep = 0
        self.__csv_output_format_raw = False

    @property
    def device_address(self):
        """Device MAC address or UUID"""
        return self.__device_address
    
    @device_address.setter
    def device_address(self, value):
        self.__device_address = value
    
    @property
    def device_name(self):
        """Device hardware name"""
        return self.__device_name
    
    @device_name.setter
    def device_name(self, value):
        self.__device_name = value

    @property
    def retry_interval(self):
        """Return interval for scanning for devices"""
        return self.__retry_interval
    
    @retry_interval.setter
    def retry_interval(self, value):
        self.__retry_interval = value

    @property
    def csv_output_enabled(self):
        """Enable output of data logging to CSV"""
        return self.__csv_output_enabled
    
    @csv_output_enabled.setter
    def csv_output_enabled(self, value):
        self.__csv_output_enabled = value

    @property
    def csv_output_file(self):
        """CSV output file"""
        return self.__csv_output_file
    
    @csv_output_file.setter
    def csv_output_file(self, value):
        self.__csv_output_file = value

    @property
    def csv_output_keep(self):
        """Number of CSV data files to keep"""
        return self.__csv_output_keep
    
    @csv_output_keep.setter
    def csv_output_keep(self, value):
        self.__csv_output_keep = value

    @property
    def valid(self):
        """Checks to make sure the parameters are valid"""
        return self.__device_name is not None or self.__device_address is not None
    
    @property
    def csv_output_raw(self):
        """Controls if the raw data values or the converted values are written into the CSV file"""
        return self.__csv_output_format_raw
    
    @csv_output_raw.setter
    def csv_output_raw(self, value):
        self.__csv_output_format_raw = value
    