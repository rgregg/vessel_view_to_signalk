"""Vessel View Mobile module"""
from logging.handlers import RotatingFileHandler
import argparse
import signal
import logging
import asyncio
import os
import yaml
from signalk_publisher import SignalKPublisher, SignalKConfig
from ble_connection import BleDeviceConnection, BleConnectionConfig

logger = logging.getLogger("vvm_monitor")

class VesselViewMobileDataRecorder:
    """Captures and records data from Vessel View Mobile BLE device"""
    
    def __init__(self):
        self.signalk_socket = None
        self.ble_connection = None

    async def main(self):
        """Main function loop for the program"""

        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGINT, lambda : asyncio.create_task(self.signal_handler()))

        config = VVMConfig()
        self.parse_config_file(config)
        self.parse_arguments(config)
        self.parse_env_variables(config)

        # enable logging
        logging.basicConfig(
            level=config.logging_level,
            format="%(asctime)-15s %(name)-8s %(levelname)s: %(message)s",
        )

        if config.logging_file is not None:
            handler = RotatingFileHandler(config.logging_file, maxBytes=5*1024*1024, backupCount=config.logging_keep)
            handler.setLevel(config.logging_level)
            formatter = logging.Formatter("%(asctime)-15s %(name)-8s %(levelname)s: %(message)s")
            handler.setFormatter(formatter)
            logging.getLogger().addHandler(handler)

        # start the main loops
        if config.bluetooth.valid:
            self.ble_connection = BleDeviceConnection(config.bluetooth, self.publish_data_func)
        else:
            logger.warning("Skipping bluetooth connection - configuration is invalid.")
            
        if config.signalk.valid:
            self.signalk_socket = SignalKPublisher(config.signalk)
        else:
            logger.warning("Skipping signalk connection - configuration is invalid.")

        background_tasks = set()
        async with asyncio.TaskGroup() as tg:
            if self.ble_connection is not None:
                task = tg.create_task(self.ble_connection.run(tg))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
            if self.signalk_socket is not None:
                task = tg.create_task(self.signalk_socket.run(tg))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
        logger.debug("All event loops are completed")

    async def publish_data_func(self, path, value):
        """Callback for publishing data to the websocket"""

        if self.signalk_socket is not None:
            await self.signalk_socket.publish_delta(path, value)
        else:
            logger.debug("Couldn't publish data - no signalk socket")

    def parse_arguments(self, config: 'VVMConfig'):
        """Parse command line arguments"""

        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-a",
            "--device-address",
            metavar="<address>",
            help="the address of the bluetooth device to connect to",
        )

        parser.add_argument(
            "--device-name",
            metavar="<name>",
            help="the name of the bluetooth device to connect to"
        )

        parser.add_argument(
            "-ws",
            "--signalk-websocket-url",
            metavar="<websocket url>",
            help="The URL for the signalk websocket service.",
        )

        parser.add_argument(
            "--username",
            help="Username for SignalK authentication"
        )

        parser.add_argument(
            "--password",
            help="Password for SignalK authentication"

        )
        
        parser.add_argument(
            "-d",
            "--debug",
            action="store_true",
            help="sets the log level to debug",
        )

        args = parser.parse_args()
        if args.signalk_websocket_url is not None:
            config.signalk.websocket_url = args.signalk_websocket_url
        if args.device_address is not None:
            config.bluetooth.device_address = args.device_address
        if args.device_name is not None:
            config.bluetooth.device_name = args.device_name
        if args.debug:
            config.logging_level = logging.DEBUG
        if args.username is not None:
            config.signalk.username = args.username
        if args.password is not None:
            config.signalk.password = args.password


    async def signal_handler(self):
        """Handle the program receiving a signal to shutdown"""

        logger.info("Gracefully shutting down...")

        if self.ble_connection is not None:
            await self.ble_connection.close()
            self.ble_connection = None
        if self.signalk_socket is not None:
            await self.signalk_socket.close()
            self.signalk_socket = None

        logger.info("Exiting.")
        asyncio.get_event_loop().stop()

    def parse_env_variables(self, config : 'VVMConfig'):
        """Parse configuration from environment variables"""

        if (signalk_url := os.getenv('VVM_SIGNALK_URL')) is not None:
            config.signalk.websocket_url = signalk_url

        if (ble_device_address := os.getenv("VVM_DEVICE_ADDRESS")) is not None:
            config.bluetooth.device_address = ble_device_address

        if (ble_device_name := os.getenv('VVM_DEVICE_NAME')) is not None:
            config.bluetooth.device_name = ble_device_name

        if os.getenv("VVM_DEBUG"):
            config.logging_level = logging.DEBUG

        if (username := os.getenv("VVM_USERNAME")) is not None:
            config.signalk.username = username

        if (password := os.getenv("VVM_PASSWORD")) is not None:
            config.signalk.password = password

    def parse_config_file(self, config: 'VVMConfig'):
        """Parse configuration from a config file"""

        # Read from the vvm_monitor.yaml file
        file_path = "config/vvm_monitor.yaml"
        if not os.path.exists(file_path):
            logger.debug("Skipping loading configuration from YAML - config file doesn't exist.")
            return
        
        try:
            with open(file_path, 'r', encoding="utf-8") as file:
                logger.info("Reading configuration from %s.", file_path)
                data = yaml.safe_load(file)
                self.parse_ble_device_config(config, data.get('ble-device'))
                self.parse_signalk_config(config, data.get('signalk'))
                self.parse_logging_config(config, data.get('logging'))

        except Exception as e:
            logger.warning("Error loading configuration file: %s", e)

    def parse_logging_config(self, config, logging_config):
        """Parse logging specific configuration"""

        if logging_config is not None:
            if (level := logging_config.get('level', "INFO")) is not None:
                level = level.upper()
                if level == "DEBUG":
                    config.logging_level = logging.DEBUG
                elif level == "WARNING":
                    config.logging_level = logging.WARNING
                elif level == "ERROR":
                    config.logging_level = logging.ERROR
                elif level == "CRITICAL":
                    config.logging_level = logging.CRITICAL
                else:
                    config.logging_level = logging.INFO
            else:
                config.logging_level = logging.INFO

            config.logging_file = logging_config.get('file', "./logs/vvm_monitor.log")
            config.logging_keep = logging_config.get('keep', 5)

    def parse_signalk_config(self, config, signalk_config):
        """Parse SignalK specific configuration"""

        if signalk_config is not None:
            config.signalk.websocket_url = signalk_config.get('websocket-url')
            config.signalk.username = signalk_config.get('username')
            config.signalk.password = signalk_config.get('password')
            config.signalk.retry_interval = signalk_config.get('retry-interval-seconds', 30)

    def parse_ble_device_config(self, config, ble_device_config):
        """Parse BLE device specific configuration"""

        if ble_device_config is not None:
            config.bluetooth.device_address = ble_device_config.get('address')
            config.bluetooth.device_name = ble_device_config.get('name')
            config.bluetooth.retry_interval = ble_device_config.get('retry-interval-seconds', 30)
            if (csv_data_recording_config := ble_device_config.get('data-recording')) is not None:
                config.bluetooth.csv_output_enabled = csv_data_recording_config.get('enabled', False)
                config.bluetooth.csv_output_file = csv_data_recording_config.get('file')
                config.bluetooth.csv_output_keep = csv_data_recording_config.get('keep', 10)
                config.bluetooth.csv_output_raw = csv_data_recording_config.get('output', 'decoded') == 'raw'

class VVMConfig:
    """Program configuration"""

    def __init__(self):
        self._ble_config = BleConnectionConfig()
        self._signalk_config = SignalKConfig()

        self._logging_level = logging.INFO
        self._logging_file = "./logs/vvm_monitor.log"
        self._logging_keep = 5
    
    @property
    def signalk(self):
        """Properties for SignalK websocket"""
        return self._signalk_config
    
    @signalk.setter
    def signalk(self, value):
        self._signalk_config = value
    
    @property
    def bluetooth(self):
        """Properties for BLE device"""

        return self._ble_config
    
    @bluetooth.setter
    def bluetooth(self, value):
        self._ble_config = value

    @property
    def logging_level(self):
        """Logging output level"""
        return self._logging_level
    
    @logging_level.setter
    def logging_level(self, value):
        self._logging_level = value

    @property
    def logging_file(self):
        """Logging output file"""
        return self._logging_file
    
    @logging_file.setter
    def logging_file(self, value):
        self._logging_file = value

    @property
    def logging_keep(self):
        """Indicates the number of log files to keep"""
        return self._logging_keep
    
    @logging_keep.setter
    def logging_keep(self, value):
        self._logging_keep = value

if __name__ == "__main__":
    try:
        asyncio.run(VesselViewMobileDataRecorder().main())
    except RuntimeError:
        pass


