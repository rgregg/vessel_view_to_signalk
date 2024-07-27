import argparse
import sys
import signal
import logging
import asyncio
import os

from signalk_publisher import SignalKPublisher
from ble_connection import VesselViewMobileReceiver

logger = logging.getLogger("vvm_logger")

class VVMConfig:
    def __init__(self):
        self._signalk_websocket_url = "ws://localhost:3000/signalk/v1/stream?subscribe=none"
        self._ble_device_address = None
        self._debug = False
    
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
    def debug(self):
        return self._debug
    
    @debug.setter
    def debug(self, value):
        self._debug = value



class VesselViewMobileDataRecorder:
    
    def __init__(self):
        self.signalk_socket = None
        self.ble_connection = None

    async def main(self):
        
        # handle sigint gracefully
        signal.signal(signal.SIGINT, self.signal_handler)

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

        # start the main loops
        if config.ble_device_address is not None:
            self.ble_connection = VesselViewMobileReceiver(config.ble_device_address, self.publish_data_func)
            
        if config.signalk_websocket_url is not None:
            self.signalk_socket = SignalKPublisher(config.signalk_websocket_url)

        background_tasks = set()
        async with asyncio.TaskGroup() as tg:
            if self.ble_connection is not None:
                task = tg.create_task(self.ble_connection.run(tg))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
            if self.signal_handler is not None:
                task = tg.create_task(self.signalk_socket.run(tg))
                background_tasks.add(task)
                task.add_done_callback(background_tasks.discard)
        logger.debug("All event loops are completed")

    async def publish_data_func(self, path, value):
        if self.signalk_socket is not None:
            self.signalk_socket.publish_delta(path, value)

    def parse_arguments(self, config: VVMConfig):
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-a",
            "--device-address",
            metavar="<address>",
            help="the address of the bluetooth device to connect to",
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
        if args.debug is not None:
            config.debug = args.debug


    def signal_handler(self, sig, frame):
        logger.info("Gracefully shutting down...")

        if self.signalk_socket is not None:
            asyncio.create_task(self.signalk_socket.close())
            self.signalk_socket = None
        if self.ble_connection is not None:
            asyncio.create_task(self.ble_connection.close())
            self.ble_connection = None

        logger.info("Exiting")
        sys.exit(0)

    def parse_env_variables(self, config : VVMConfig):
        signalk_url = os.getenv("VVM_SIGNALK_URL")
        if signalk_url is not None:
            config.signalk_websocket_url = signalk_url

        ble_device_address = os.getenv("VVM_DEVICE_ADDRESS")
        if ble_device_address is not None:
            config.ble_device_address = ble_device_address

        debug = os.getenv("VVM_DEBUG")
        if debug is not None:
            config.debug = debug


if __name__ == "__main__":
    asyncio.run(VesselViewMobileDataRecorder().main())


