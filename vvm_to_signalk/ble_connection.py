"""BLE connection module"""

import asyncio
import logging

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_16, uuid16_dict
from bleak.exc import BleakCharacteristicNotFoundError
from .futures_queue import FuturesQueue
from .config_decoder import ConfigDecoder, EngineDataReceiver
from .data_dictionary import DataDictionary, decode_notification, build_channel_config
from .fault_decoder import parse_fault

logger = logging.getLogger(__name__)
BLE_TIMEOUT = 30

# offline alarm items to request if not already streamed
OFFLINE_FAULT_ITEM_IDS = [87, 97, 106]   # Guardian Cause, Seven Function Gauge, MIL

_CHANNEL_UUID_TEMPLATE = "000001{:02x}-0000-1000-8000-ec55f9f5b963"  # 0x02..0x10 -> chars

class BleDeviceConnection:
    """Handles the connection to the BLE hardware device"""

    def __init__(self, config: 'BleConnectionConfig', health_status):
        logger.debug("Created a new instance of decoder class")
        self.__config = config
        self.__abort = False
        self.__cancel_signal = asyncio.Future()
        self.__notification_queue = FuturesQueue()
        self.__task_group = None
        self.__health = health_status
        self.__last_message_time = None
        self.__data_receivers = []
        self.__publish_tasks = set()
        self._dictionary = DataDictionary.load()
        self._max_engines = 4
        self._active_engine_ids = None   # set from data-item 10000
        self._last_active_ids = None     # set from runtime channel-map parse
        self._unparsed_seen = set()      # channel keys already warned about this connection

    def accept_data_receiver(self, receiver: EngineDataReceiver) -> None:
        """Add a new data receiver to the collection"""
        self.__data_receivers.append(receiver)

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

    def device_disconnected(self, _client: BleakClient):
        """ Handle when the BLE device disconnects """
        self._set_health(False, "BLE device disconnected")
        # exit the scan loop so we can go back to device discovery
        if not self.__cancel_signal.done():
            self.__cancel_signal.set_result(None) 

    async def run(self, task_group):
        """Main run loop for detecting the BLE device and processing data from it"""
        self.__task_group = task_group
        
        while not self.__abort:
            # Loop on device discovery
            logger.info("Scanning for BLE devices")
            found_device = None
            while found_device is None:
                found_device = await self._scan_for_device()
                if self.__abort:
                    self._set_health(False, "device discovery scan aborted")
                    logger.info("Discovery scan aborted")
                    return
                
                if found_device is not None:
                    # We have a device!
                    logger.info("Found BLE device %s", found_device)
                    break

            # Run until the device is disconnected or the process is cancelled
            logger.info("Starting device data loop")
            
            # configure the device and loop until abort or disconnect
            connected = await self._device_init_and_loop(found_device)

            # If we never managed to connect, back off before retrying so a
            # persistent device-side error doesn't busy-loop the scan/connect cycle.
            if not connected and not self.__abort:
                logger.info("Connection attempt failed; backing off for %s seconds before retrying",
                            self.retry_interval)
                await asyncio.sleep(self.retry_interval)

            logger.info("Returning to device scan loop")

    def _set_health(self, value: bool, message: str = None):
        """Sets the health of the BLE connection"""
        self.__health["bluetooth"] = value
        if message is None:
            self.__health.pop("bluetooth_error", None)
        else:
            self.__health["bluetooth_error"] = message
            logger.info(message)


    async def _device_init_and_loop(self, device) -> bool:
        """Initalize BLE device and loop receiving data.

        Returns True if a connection was established (and later disconnected),
        or False if the attempt failed before connecting. The caller uses this
        to decide whether to back off before retrying.
        """
        monitor_task = None
        connected = False
        try:
            async with BleakClient(device,
                                    disconnected_callback=self.device_disconnected,
                                    timeout=self.__config.connection_timeout
                                    ) as client:

                self._set_health(True, "Connected to device")
                connected = True
                self._reset_unparsed_tracking()

                logger.info("Retrieving device identification metadata...")
                await self._retrieve_device_info(client)
                    
                logger.info("Initalizing VVM...")
                await self._initalize_vvm(client)
                    
                logger.info("Configuring data streaming notifications...")
                await self._setup_data_notifications(client)
                await self._request_offline_fault_channels(client, self._last_active_ids or [])

                logger.info("Enabling data streaming from BLE device")
                await self._set_streaming_mode(client, enabled=True)

                # Start the streaming monitor if a timeout is configured
                if self.__config.streaming_timeout > 0:
                    monitor_task = self.__task_group.create_task(self._monitor_streaming())

                # run until the device is disconnected or
                # the operation is terminated
                
                await self.__cancel_signal
                logger.info("Cancel signal received - exiting data loop")

        except Exception as e:
            self._set_health(False, f"Device error: {e}")
        finally:
            if monitor_task:
                monitor_task.cancel()
            self.__cancel_signal = asyncio.Future()

        return connected

    async def _monitor_streaming(self):
        """Monitors the streaming data and cancels the connection if it times out"""
        while not self.__abort:
            await asyncio.sleep(self.__config.streaming_timeout)
            if self.__last_message_time is None:
                continue

            if (asyncio.get_event_loop().time() - self.__last_message_time) > self.__config.streaming_timeout:
                logger.warning("Streaming data timed out. Disconnecting...")
                self._set_health(False, "Streaming data timed out")
                if not self.__cancel_signal.done():
                    self.__cancel_signal.set_result(None)
                break

    async def _scan_for_device(self):
        """Scan for BLE device with matching info"""

        if self.device_address is not None:
            logger.info("Scanning for bluetooth device with ID: '%s'...", self.device_address)
        elif self.device_name is not None:
            logger.info("Scanning for bluetooth device with name: '%s'...", self.device_name)

        self._set_health(True, "Scanning for device")
                
        async with BleakScanner() as scanner:
            async for device_info in scanner.advertisement_data():
                device = device_info[0]
                logger.debug("Found BLE device: %s", device)
                if self.device_address is not None and device.address == self.device_address:
                    logger.info("Found matching device by address: %s", device)
                    return device
                if self.device_name is not None and device.name == self.device_name:
                    logger.info("Found matching device by name: %s", device)
                    return device
        return None

    async def close(self):
        """
        Disconnect from the BLE device and clean up anything we were doing to close down the loop
        """

        logger.info("Disconnecting from bluetooth device...")
        self.__abort = True
        if not self.__cancel_signal.done():
            self.__cancel_signal.set_result(None)  # cancels the loop if we have a device and disconnects
        logger.debug("completed close operations")
        self._set_health(False, "shutting down")

    async def _setup_data_notifications(self, client: BleakClient):
        """
        Enable BLE notifications for the charateristics that we're interested in
        """

        logger.debug("enabling notifications on data chars")

        # Subscribe only to "notify" characteristics. The VVM streams all
        # engine data and fault notifications over notify-type characteristics.
        # The indicate-type control characteristics it also exposes (e.g.
        # 0x301/0x302/0x401 and the standard 0x2a05 Service Changed) reject a
        # CCCD subscribe with ATT error 0x0e and then drop the BLE link, which
        # stops streaming from ever starting. Subscribing to "indicate" here
        # therefore breaks the whole connection, so it is intentionally omitted.
        # Regression: test_setup_data_notifications_skips_indicate_only.
        for service in client.services:
            for characteristic in service.characteristics:
                props = characteristic.properties
                if "notify" in props:
                    try:
                        await client.start_notify(characteristic.uuid, self.notification_handler)
                        logger.debug("Subscribed to %s", characteristic.uuid)
                    except Exception as e:
                        logger.warning("Unable to subscribe to %s: %s", characteristic.uuid, e)
    

    async def _request_offline_fault_channels(self, client, active_ids):
        """Configure spare channel slots to stream offline alarm items."""
        # Channel characteristics are 0x102..0x110 (slots 1..15).
        slot = len(active_ids)  # first unused slot index (0-based -> char 0x102+slot)
        for item_id in OFFLINE_FAULT_ITEM_IDS:
            if item_id in active_ids:
                continue
            if slot >= 15:
                logger.warning("No spare channel slots for offline fault item %s", item_id)
                break
            char_uuid = _CHANNEL_UUID_TEMPLATE.format(0x02 + slot)
            cfg = build_channel_config(item_id, engines=self._max_engines)
            try:
                # Notifications on all channel characteristics were already enabled by
                # _setup_data_notifications; we only need to write the channel config here.
                await client.write_gatt_char(char_uuid, cfg, response=True)
                logger.info("Requested offline fault item %s on %s", item_id, char_uuid)
                slot += 1
            except Exception as e:
                logger.warning("Could not request fault item %s on %s: %s", item_id, char_uuid, e)

    def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """Handles BLE notifications and indications."""
        self.__last_message_time = asyncio.get_event_loop().time()
        uuid = characteristic.uuid
        # Guard the hex() conversion: this runs on every notification, so avoid
        # paying for it when debug logging is disabled.
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug("Notification UUID %s data %s", uuid, data.hex())

        # Fault Alert characteristic is handled separately (Task 8).
        if uuid == UUIDs.DEVICE_201_UUID:
            self._handle_fault_notification(bytes(data))
            return

        # Config / UserVar exchanges are resolved via registered futures, not decoded
        # as channel data (avoids "unmatched data" noise on every engine notification).
        if uuid in (UUIDs.DEVICE_CONFIG_UUID, UUIDs.DEVICE_NEXT_UUID):
            self._trigger_event_listener(uuid, data, True)
            return

        item, values = decode_notification(bytes(data), self._dictionary, self._max_engines)
        if item is None:
            self._log_unparsed_channel_data(uuid, bytes(data))
            return
        if item.id == 10000:
            self._update_active_engines(bytes(data))
            return
        for index, value in enumerate(values):
            engine_id = index + 1
            if self._active_engine_ids is not None and engine_id not in self._active_engine_ids:
                continue
            self._publish_engine_value(item, engine_id, value)

    def _reset_unparsed_tracking(self):
        """Clear the per-connection memory of already-warned channel data so a
        fresh connection re-surfaces any still-undecodable notifications."""
        self._unparsed_seen.clear()

    def _log_unparsed_channel_data(self, uuid: str, data: bytes):
        """Surface a channel notification we couldn't decode, once per distinct
        item-id (or raw payload, if too short to carry one) per connection.

        Channels stream at ~20 Hz and an unknown item's value bytes change on
        every notification, so we dedup on the item-id rather than the full
        payload to make novel/unknown data visible without flooding the log.
        """
        if len(data) >= 2:
            key = ("id", int.from_bytes(data[:2], byteorder="little"))
            what = f"item-id {key[1]}"
        else:
            key = ("raw", data.hex())
            what = "short payload"
        if key in self._unparsed_seen:
            return
        self._unparsed_seen.add(key)
        logger.warning("Unparsed channel data on %s (%s): %s", uuid, what, data.hex())

    def _publish_engine_value(self, item, engine_id, value):
        """Dispatch a decoded engine value to all registered receivers."""
        loop = asyncio.get_event_loop()
        for receiver in self.__data_receivers:
            self._track_task(loop.create_task(receiver.accept_engine_data(item, engine_id, value)))

    def _update_active_engines(self, data: bytes):
        """Parse data-item 10000 bitfield to track which engine IDs are active."""
        # data-item 10000 is a 1-byte bitfield after the 2-byte id
        if len(data) >= 3:
            bits = data[2]
            self._active_engine_ids = {e for e in (1, 2, 3, 4) if bits & (1 << (e - 1))}
            logger.info("Active engines: %s", sorted(self._active_engine_ids))

    def _handle_fault_notification(self, data: bytes):
        """Parse a fault alert payload and dispatch it to all registered receivers."""
        fault = parse_fault(data)
        if fault is None:
            return
        logger.info("Fault received: %s", fault)
        loop = asyncio.get_event_loop()
        for receiver in self.__data_receivers:
            self._track_task(loop.create_task(receiver.accept_fault(fault)))

    def _track_task(self, task: asyncio.Task):
        """Retain a strong reference to a fire-and-forget receiver task so it
        isn't garbage-collected before it runs, and observe its result so
        receiver errors aren't silently swallowed."""
        self.__publish_tasks.add(task)
        task.add_done_callback(self._publish_task_done)

    def _publish_task_done(self, task: asyncio.Task):
        """Done-callback for receiver tasks: drop the reference and log failures."""
        self.__publish_tasks.discard(task)
        if task.cancelled():
            return
        if (error := task.exception()) is not None:
            logger.warning("Error dispatching data to receiver: %s", error)

    async def _initalize_vvm(self, client: BleakClient):
        """
        Sets up the VVM based on the patters from the mobile application. This is likely
        unnecessary and is just being used to receive data from the device but we need
        more signal to know for sure.
        """

        logger.debug("initalizing VVM device...")

        # enable indiciations on 001
        await self._set_streaming_mode(client, enabled=False)

        # Indicates which parameters are available on the device
        if (engine_params := await self._request_device_parameter_config(client)) is not None:
            self.update_active_items(engine_params)
        else:
            logging.warning("No engine parameters were received. Will continue to try to connect.")

        data = bytes([0x10, 0x27, 0x0])
        result = await self._request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        if (expected_result := '00102701010001') != result.hex():
            logger.warning("configuration_data_1 response: %s, expected: 00102701010001", result.hex())

        data = bytes([0xCA, 0x0F, 0x0])
        expected_result = "00ca0f01010000"
        result = await self._request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        if (expected_result != result.hex()):
            logger.warning("configuration_data_2 response: %s, expected: %s", result.hex(), expected_result)

        data = bytes([0xC8, 0x0F, 0x0])
        result = await self._request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        if (expected_result := '00c80f01040000000000') != result.hex():
            logger.warning("configuration_data_3 response: %s, expected: %s", result.hex(), expected_result)

    def update_active_items(self, item_ids: list[int]) -> None:
        """Propagate the active data-item IDs to all registered receivers."""
        self._last_active_ids = item_ids
        for receiver in self.__data_receivers:
            receiver.update_active_items(item_ids)

    async def _set_streaming_mode(self, client: BleakClient, enabled):
        """ Enable or disable engine data streaming via characteristic notifications """

        if enabled:
            data = bytes([0xD, 0x1])
        else:
            data = bytes([0xD, 0x0])

        await client.write_gatt_char(UUIDs.DEVICE_CONFIG_UUID, data, response=True)

    async def _request_device_parameter_config(self, client: BleakClient) -> list[int]:
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
            async with asyncio.timeout(BLE_TIMEOUT):
                await client.write_gatt_char(uuid, data, response=True)
                result_data = await asyncio.gather(*future_data)

                decoder = ConfigDecoder()
                decoder.add(result_data)
                decoder.combine_and_parse_data()
                return decoder.active_data_item_ids()
            
        except TimeoutError:
            logger.info("timeout waiting for configuration data to return")
            return None



    async def _request_configuration_data(self, client: BleakClient, uuid: str, data: bytes):
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
            async with asyncio.timeout(BLE_TIMEOUT):
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


    def _trigger_event_listener(self, uuid: str, data, raw_bytes_from_device):
        """
        Trigger the waiting Futures when data is received
        """

        logger.debug("triggering event listener for %s with data: %s", uuid, data)
        matched = self.__notification_queue.trigger(uuid, data)
        if not matched:
            logger.warning("Unmatched data for UUID %s with data %s", uuid, data)
        
        # handle promises for data based on the uuid + first byte of the response if raw data
        if raw_bytes_from_device:
            try:
                key_id = f"{uuid}+{int(data[0])}"
                logger.debug("triggering notification handler on id: %s", key_id)
                matched = self.__notification_queue.trigger(key_id, data)
                if not matched:
                    logger.warning("Unmatched data for %s with data %s", key_id, data.hex())
            except Exception as e:
                logger.warning("Exception triggering notification: %s", e)

    async def _read_char(self, client: BleakClient, uuid: str):
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
            


    async def _retrieve_device_info(self, client: BleakClient):
        """
        Retrieves the BLE standard data for the device. Characteristics that the
        device doesn't expose come back as None and are reported as unavailable
        rather than crashing initialization.
        """

        logger.info("Model Number: %s",
                    self._decode_string_char(await self._read_char(client, UUIDs.MODEL_NBR_UUID)))
        logger.info("Device Name: %s",
                    self._decode_string_char(await self._read_char(client, UUIDs.DEVICE_NAME_UUID)))
        logger.info("Manufacturer Name: %s",
                    self._decode_string_char(await self._read_char(client, UUIDs.MANUFACTURER_NAME_UUID)))
        logger.info("Firmware Revision: %s",
                    self._decode_string_char(await self._read_char(client, UUIDs.FIRMWARE_REV_UUID)))

    @staticmethod
    def _decode_string_char(value):
        """Decode a string characteristic value, tolerating absent (None) data."""
        if value is None:
            return "<unavailable>"
        return "".join(chr(c) for c in value)


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


class BleConnectionConfig:
    """Configuration information for the BLE connection"""
    def __init__(self, data: dict = None):
        self.__device_address = None
        self.__device_name = None
        self.__retry_interval = 30
        self.__connection_timeout = 10.0
        self.__streaming_timeout = 10.0
        if data is not None:
            self.read(data)

    def read(self, data: dict):
        """Read data from a dictionary"""
        if data is None:
            return
        
        self.__device_address = data.get('address', self.__device_address)
        self.__device_name = data.get('name', self.__device_name)
        self.__retry_interval = data.get('retry-interval-seconds', self.__retry_interval)
        self.__connection_timeout = data.get('connection-timeout-seconds', self.__connection_timeout)
        self.__streaming_timeout = data.get('streaming-timeout-seconds', self.__streaming_timeout)

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
    def valid(self):
        """Checks to make sure the parameters are valid"""
        return self.__device_name is not None or self.__device_address is not None
    
    @property
    def connection_timeout(self):
        """Timeout for the BLE connection"""
        return self.__connection_timeout

    @connection_timeout.setter
    def connection_timeout(self, value):
        self.__connection_timeout = value

    @property
    def streaming_timeout(self):
        """Timeout for the BLE streaming"""
        return self.__streaming_timeout

    @streaming_timeout.setter
    def streaming_timeout(self, value):
        self.__streaming_timeout = value
    
