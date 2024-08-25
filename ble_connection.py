import asyncio
import logging

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_16, uuid16_dict
from bleak.exc import BleakCharacteristicNotFoundError

from csv_writer import CSVWriter
from futures_queue import FuturesQueue

from config_decoder import EngineParameter, ConfigDecoder, EngineParameterType

logger = logging.getLogger(__name__)

class BleDeviceConnection:

    rescan_timeout_seconds = 10

    def __init__(self, config: 'BleConnectionConfig', publish_delta_func):
        logger.debug("Created a new instance of decoder class")
        self.__config = config
        
        self.__device = None
        self.__abort = False
        self.__cancel_signal = asyncio.Future()
        self.__publish_delta_func = publish_delta_func
        self.__notification_queue = FuturesQueue()
        self.__engine_parameters = []
        self.__csv_writer = None

    @property
    def device_address(self):
        return self.__config.device_address
    
    @property
    def device_name(self):
        return self.__config.device_name
    
    @property
    def retry_interval(self):
        return self.__config.retry_interval
    
    @property
    def engine_parameters(self):
        return self.__engine_parameters
    
    @property
    def csv_writer(self):
        return self.__csv_writer
    
    @csv_writer.setter
    def csv_writer(self, value):
        self.__csv_writer = value
    
   
    def disconnected(self):
        logger.info("BLE device has disconnected")
        self.__cancel_signal.done()


    """
    Main run loop for detecting the BLE device and processing data from it
    """
    async def run(self, task_group):
        #loop = asyncio.get_event_loop()
        
        while not self.__abort:
            # Loop on device discovery
            while self.__device is None:
                if self.device_address is not None:
                    logger.info(f"Scanning for bluetooth device with ID: '{self.device_address}'...")
                elif self.device_name is not None:
                    logger.info(f"Scanning for bluetooth device with name: '{self.device_name}'...")
                
                async with BleakScanner() as scanner:
                    async for tuple in scanner.advertisement_data():
                        device = tuple[0]
                        logger.info(f"Found BLE device: {device}")
                        if self.device_address is not None and device.address == self.device_address:
                            logger.info(f"Found matching device by address: {device}")
                            self.__device = device
                            break
                        if self.device_name is not None and device.name == self.device_name:
                            logger.info(f"Found matching device by name: {device}")
                            self.__device = device
                            break

                if self.__abort:
                    logger.debug("Aborting BLE connection and exiting loop")
                    return

            # Run until the device is disconnected or the process is cancelled
            logger.info(f"Found BLE device {self.__device}")
            try:
                async with BleakClient(self.__device,
                                    disconnected_callback=self.disconnected()
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
                    self.__cancel_signal = asyncio.Future()
                    await self.__cancel_signal
            except Exception as e:
                logger.warn(f"Exception from BLE connection: {e}")

            self.__device = None
        #end of self.abort loop


        def device_disconnected(self):
            # handle the device disconnecting from the system
            logger.warn("BLE device was disconnected. Will attempt to reconnect.")
            self.abort = False
            self.cancel_signal.done()

    """
    Configure the CSV output logger if enabled - with the engine parameters the connected
    device supports.
    """
    def configure_csv_output(self, engine_params):
        
        if self.__config.csv_output_enabled:
            fieldnames = [ "timestamp" ]
            for param in engine_params:
                if param.enabled:
                    fieldnames.append(param.signalk_path)

            self.csv_writer = CSVWriter(self.__config.csv_output_file, fieldnames)
        else:
            self.csv_writer = None

    """
    Disconnect from the BLE device and clean up anything we were doing to close down the loop
    """
    async def close(self):
        logger.info("Disconnecting from bluetooth device...")
        self.__abort = True
        self.__cancel_signal.done()  # cancels the loop if we have a device and disconnects
        logger.debug("completed close operations")

    """
    Enable BLE notifications for the charateristics that we're interested in
    """
    async def setup_data_notifications(self, client: BleakClient):
        logger.debug("enabling notifications on data chars")
        
        # subscribe to all available charactieristics on the device
        services = await client.get_services()

        # Iterate over all characteristics in all services
        for service in services:
            for characteristic in service.characteristics:
                if "notify" in characteristic.properties:
                    await client.start_notify(characteristic.uuid, self.notification_handler)
                    logger.debug(f"Subscribed to {characteristic.uuid}")

    """
    Handles BLE notifications and indications
    """
    def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        #Simple notification handler which prints the data received
        uuid = characteristic.uuid
        logger.debug(f"Received notification from BLE - UUID: {uuid}; data: {data.hex()}")

        # If the notification is about an engine property, we need to push
        # that information into the SignalK client as a property delta

        data_header = int.from_bytes(data[:2], byteorder='little')
        logger.info(f"data_header: {data_header}")
        matching_param = next((element for element in self.__engine_parameters if element.notification_header == data_header), None)
        if matching_param:
            # decode data from byte array to underlying value (remove header bytes and convert to int)
            decoded_value = self.strip_header_and_convert_to_int(data)
            self.trigger_event_listener(uuid, decoded_value, False)
            self.convert_and_publish_data(matching_param, decoded_value)

            logger.info(f"Received data for {matching_param.signalk_path} with value {decoded_value}")
            try:
                if self.csv_writer is not None:
                    if self.__config.csv_output_raw:
                        self.csv_writer.update_property(matching_param.signalk_path, data.hex())
                    else:
                        self.csv_writer.update_property(matching_param.signalk_path, decoded_value)
            except Exception as e:
                logger.warn(f"Unable to write data to CSV: {e}")
        else:
            logger.debug(f"Triggered notification for UUID: {uuid} with data {data.hex()}")
            self.trigger_event_listener(uuid, data, True)

    """
    Converts data using the engine paramater conversion function into the signal k
    expected format and then publishes the data using the singalK API connector
    """
    def convert_and_publish_data(self, engine_param: EngineParameter, decoded_value):
        path = engine_param.get_signalk_path()
        convert_func = Conversion.conversion_for_parameter_type(engine_param.parameter_type)
        output_value = convert_func(decoded_value)
        if path:
            logger.debug(f"Publishing value '{output_value}' to path '{path}'")
            self.publish_to_signalk(path, output_value)
        else:
            logger.debug(f"No path found for parameter: '{engine_param}' with value '{output_value}'")


    """
    Parses the byte stream from a device notification, strips
    the header bytes and converts the value to an integer with 
    little endian byte order
    """
    def strip_header_and_convert_to_int(self, data):
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
        if self.__publish_delta_func is not None:
            loop = asyncio.get_event_loop()
            loop.create_task(self.__publish_delta_func(path, value))
        else:
            logger.info("Cannot publish to signalk")

    """
    Sets up the VVM based on the patters from the mobile application. This is likely
    unnecessary and is just being used to receive data from the device but we need
    more signal to know for sure.
    """
    async def initalize_vvm(self, client: BleakClient):
        logger.debug("initalizing VVM device...")

        # read 0302 as byte array
        # try:
        #     data1 = await self.read_char(client, UUIDs.DEVICE_STARTUP_UUID)
        #     logger.info("Initial configuration read %s", data1.hex())
        # except Exception:
        #     pass

        # enable indiciations on 001
        await self.set_streaming_mode(client, enabled=False)

        # Indicates which parameters are available on the device
        self.__engine_parameters = await self.request_device_parameter_config(client)
        self.configure_csv_output(self.__engine_parameters)

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
    Writes the request to send the parameter conmfiguration from the device
    via indications on characteristic DEVICE_CONFIG_UUID. This data is returned
    over a series of indications on the DEVICE_CONFIG_UUID charateristic.
    """
    async def request_device_parameter_config(self, client: BleakClient):
        
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
                engine_parameters = decoder.parse_data()
                logger.info(f"Device parameters: {engine_parameters}")
                return engine_parameters
            
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


    """
    Generate a promise for the data that will be received in the future for a given characteristic
    """
    def future_data_for_uuid(self, uuid: str, key = None):
        logger.debug("future promise for data on uuid: %s, key: %s", uuid, key)
        id = uuid
        if key is not None:
            id = f"{uuid}+{key}"

        return self.__notification_queue.register(id)


    """
    Trigger the waiting Futures when data is received
    """
    def trigger_event_listener(self, uuid: str, data, raw_bytes_from_device):
        logger.debug(f"triggering event listener for {uuid} with data: {data}")
        self.__notification_queue.trigger(uuid, data)
        
        # handle promises for data based on the uuid + first byte of the response if raw data
        if raw_bytes_from_device:
            try:
                id = f"{uuid}+{int(data[0])}"
                logger.debug(f"triggering notification handler on id: {id}")
                self.__notification_queue.trigger(id, data)
            except Exception as e:
                logger.warning(f"Exception triggering notification: {e}")

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

        model_number = await self.read_char(client, UUIDs.MODEL_NBR_UUID)
        logger.info("Model Number: {0}".format("".join(map(chr, model_number))))
        
        device_name = await self.read_char(client, UUIDs.DEVICE_NAME_UUID)
        logger.info("Device Name: {0}".format("".join(map(chr, device_name))))

        manufacturer_name = await self.read_char(client, UUIDs.MANUFACTURER_NAME_UUID)
        logger.info("Manufacturer Name: {0}".format("".join(map(chr, manufacturer_name))))

        firmware_revision = await self.read_char(client, UUIDs.FIRMWARE_REV_UUID)
        logger.info("Firmware Revision: {0}".format("".join(map(chr, firmware_revision))))


class UUIDs:
    uuid16_lookup = {v: normalize_uuid_16(k) for k, v in uuid16_dict.items()}

    """Standard UUIDs from BLE protocol"""
    MODEL_NBR_UUID = uuid16_lookup["Model Number String"]
    DEVICE_NAME_UUID = uuid16_lookup["Device Name"]
    FIRMWARE_REV_UUID = uuid16_lookup["Firmware Revision String"]
    MANUFACTURER_NAME_UUID = uuid16_lookup["Manufacturer Name String"]

    """Manufacturer specific UUIDs"""
    DEVICE_STARTUP_UUID = "00000302-0000-1000-8000-ec55f9f5b963"
    DEVICE_CONFIG_UUID = "00000001-0000-1000-8000-ec55f9f5b963"
    DEVICE_NEXT_UUID = "00000111-0000-1000-8000-ec55f9f5b963"
    DEVICE_201_UUID = "00000201-0000-1000-8000-ec55f9f5b963"

    # """Engine data parameters"""
    # ENGINE_RPM_UUID = "00000102-0000-1000-8000-ec55f9f5b963"
    # COOLANT_TEMPERATURE_UUID = "00000103-0000-1000-8000-ec55f9f5b963"
    # BATTERY_VOLTAGE_UUID = "00000104-0000-1000-8000-ec55f9f5b963"
    # UNK_105_UUID = "00000105-0000-1000-8000-ec55f9f5b963"
    # ENGINE_RUNTIME_UUID = "00000106-0000-1000-8000-ec55f9f5b963"
    # CURRENT_FUEL_FLOW_UUID = "00000107-0000-1000-8000-ec55f9f5b963"
    # UNK_108_UUID = "00000108-0000-1000-8000-ec55f9f5b963"
    # UNK_109_UUID = "00000109-0000-1000-8000-ec55f9f5b963"
    # OIL_PRESSURE_UUID = "0000010a-0000-1000-8000-ec55f9f5b963"
    # UNK_10B_UUID = "0000010b-0000-1000-8000-ec55f9f5b963"
    # UNK_10C_UUID = "0000010c-0000-1000-8000-ec55f9f5b963"
    # UNK_10D_UUID = "0000010d-0000-1000-8000-ec55f9f5b963"   

class Conversion:
    def rpm_to_hertz(rpm):
        return rpm / 60.0

    def celsius_to_kelvin(celsius):
        return celsius + 273.15

    def minutes_to_seconds(minutes):
        return minutes * 60

    def centiliters_to_cubic_meters(cl_per_hour):
        # Conversion factors
        m3_per_cl = 0.00001
        seconds_per_hour = 3600.0
        
        m3_per_second = cl_per_hour * m3_per_cl / seconds_per_hour
        return m3_per_second

    def decapascals_to_pascals(value):
        return value * 10
    
    def millivolts_to_volts(value):
        return value / 1000.0
    
    def identity_function(value):
        return value
    
    def conversion_for_parameter_type(param: EngineParameterType):
        if param == EngineParameterType.BATTERY_VOLTAGE:
            return Conversion.millivolts_to_volts
        elif param == EngineParameterType.COOLANT_TEMPERATURE:
            return Conversion.celsius_to_kelvin
        elif param == EngineParameterType.CURRENT_FUEL_FLOW:
            return Conversion.centiliters_to_cubic_meters
        elif param == EngineParameterType.ENGINE_RPM:
            return Conversion.rpm_to_hertz
        elif param == EngineParameterType.ENGINE_RUNTIME:
            return Conversion.minutes_to_seconds
        elif param == EngineParameterType.OIL_PRESSURE:
            return Conversion.decapascals_to_pascals
        else:
            logger.error(f"Unknown conversion for unknown datatype: {param}")
            return Conversion.identity_function


        

class BleConnectionConfig:
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
        return self.__device_address
    
    @device_address.setter
    def device_address(self, value):
        self.__device_address = value
    
    @property
    def device_name(self):
        return self.__device_name
    
    @device_name.setter
    def device_name(self, value):
        self.__device_name = value

    @property
    def retry_interval(self):
        return self.__retry_interval
    
    @retry_interval.setter
    def retry_interval(self, value):
        self.__retry_interval = value

    @property
    def csv_output_enabled(self):
        return self.__csv_output_enabled
    
    @csv_output_enabled.setter
    def csv_output_enabled(self, value):
        self.__csv_output_enabled = value

    @property
    def csv_output_file(self):
        return self.__csv_output_file
    
    @csv_output_file.setter
    def csv_output_file(self, value):
        self.__csv_output_file = value

    @property
    def csv_output_keep(self):
        return self.__csv_output_keep
    
    @csv_output_keep.setter
    def csv_output_keep(self, value):
        self.__csv_output_keep = value

    @property
    def valid(self):
        return self.__device_name is not None or self.__device_address is not None
    

    @property
    def csv_output_raw(self):
        return self.__csv_output_format_raw
    
    @csv_output_raw.setter
    def csv_output_raw(self, value):
        self.__csv_output_format_raw = value
    