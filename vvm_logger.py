import argparse
import sys
import signal
import logging
import asyncio
import os
from logging.handlers import RotatingFileHandler

from signalk_publisher import SignalKPublisher
from ble_connection import VesselViewMobileReceiver

logger = logging.getLogger(__name__)

class VVMConfig:
    def __init__(self):
        self._signalk_websocket_url = "ws://localhost:3000/signalk/v1/stream?subscribe=none"
        self._ble_device_address = None
        self._ble_device_name = None
        self._debug = False
        self._username = None
        self._password = None
    
    @property
    def signalk_websocket_url(self):
        return self._signalk_websocket_url
    
    @signalk_websocket_url.setter
    def signalk_websocket_url(self, value):
        self._signalk_websocket_url = value
    
    @property
    def ble_device_address(self):
        return self._ble_device_address
    
    @ble_device_address.setter
    def ble_device_address(self, value):
        self._ble_device_address = value

    @property
    def ble_device_name(self):
        return self._ble_device_name
    
    @ble_device_name.setter
    def ble_device_name(self, value):
        self._ble_device_name = value
    
    @property
    def debug(self):
        return self._debug
    
    @debug.setter
    def debug(self, value):
        self._debug = value

    @property
    def username(self):
        return self._username

    @username.setter
    def username(self, value):
        self._username = value

    @property
    def password(self):
        return self._password

    @password.setter
    def password(self, value):
        self._password = value



class VesselViewMobileDataRecorder:
    
    def __init__(self):
        self.signalk_socket = None
        self.ble_connection = None

    async def main(self):
        
        # handle sigint gracefully
        #signal.signal(signal.SIGINT, lambda signal, frame: asyncio.create_task(self.signal_handler(signal, frame)))
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(signal.SIGINT, lambda : asyncio.create_task(self.signal_handler()))

        config = VVMConfig()

        # parse env vars
        self.parse_env_variables(config)

        # parse arguments
        self.parse_arguments(config)

        # enable logging
        log_level = logging.DEBUG if config.debug else logging.INFO
        logging.basicConfig(
            level=log_level,
            format="%(asctime)-15s %(name)-8s %(levelname)s: %(message)s",
        )

        handler = RotatingFileHandler("logs/vvm_monitor.log", maxBytes=5*1024*1024, backupCount=5)
        handler.setLevel(log_level)
        formatter = logging.Formatter("%(asctime)-15s %(name)-8s %(levelname)s: %(message)s")
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)

        # start the main loops
        if config.ble_device_name is not None or config.ble_device_address is not None:
            self.ble_connection = VesselViewMobileReceiver(config.ble_device_address, config.ble_device_name, self.publish_data_func)
            
        if config.signalk_websocket_url is not None:
            self.signalk_socket = SignalKPublisher(config.signalk_websocket_url, config.username, config.password)

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
        if self.signalk_socket is not None:
            await self.signalk_socket.publish_delta(path, value)
        else:
            logger.debug("Couldn't publish data - no signalk socket")

    def parse_arguments(self, config: VVMConfig):
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
            "-d",
            "--debug",
            action="store_true",
            help="sets the log level to debug",
        )

        args = parser.parse_args()
        if args.signalk_websocket_url is not None:
            config.signalk_websocket_url = args.signalk_websocket_url
        if args.device_address is not None:
            config.ble_device_address = args.device_address
        if args.device_name is not None:
            config.ble_device_name = args.device_name
        if args.debug is not None:
            config.debug = args.debug


    async def signal_handler(self):
        logger.info("Gracefully shutting down...")

        if self.ble_connection is not None:
            await self.ble_connection.close()
            self.ble_connection = None
        if self.signalk_socket is not None:
            await self.signalk_socket.close()
            self.signalk_socket = None

        logger.info("Exiting.")
        asyncio.get_event_loop().stop()

    def parse_env_variables(self, config : VVMConfig):
        signalk_url = os.getenv("VVM_SIGNALK_URL")
        if signalk_url is not None:
            config.signalk_websocket_url = signalk_url

        ble_device_address = os.getenv("VVM_DEVICE_ADDRESS")
        if ble_device_address is not None:
            config.ble_device_address = ble_device_address

        ble_device_name = os.getenv("VVM_DEVICE_NAME")
        if ble_device_name is not None:
            config.ble_device_name = ble_device_name

        debug = os.getenv("VVM_DEBUG")
        if debug is not None:
            config.debug = debug

        username = os.getenv("VVM_USERNAME")
        if username is not None:
            config.username = username

        password = os.getenv("VVM_PASSWORD")
        if password is not None:
            config.password = password


if __name__ == "__main__":
    try:
        asyncio.run(VesselViewMobileDataRecorder().main())
    except RuntimeError:
        pass


