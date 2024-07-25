import argparse
import sys
import signal
import logging
import asyncio

from signalk_publisher import SignalKPublisher
from ble_connection import VesselViewMobileReceiver

logger = logging.getLogger("vvm_logger")

class VesselViewMobileDataRecorder:
    
    def __init__(self):
        self.signalk_socket = None
        self.ble_connection = None

    async def main(self):
        
        # handle sigint gracefully
        signal.signal(signal.SIGINT, self.signal_handler)

        # parse arguments
        args = self.parse_arguments()

        # enable logging
        log_level = logging.DEBUG if args.debug else logging.INFO
        logging.basicConfig(
            level=log_level,
            format="%(asctime)-15s %(name)-8s %(levelname)s: %(message)s",
        )

        # start the main loops
        if args.device_address is not None and not args.skip_ble:
            self.ble_connection = VesselViewMobileReceiver(args.device_address, self.publish_data_func)
            
        if args.signalk_websocket_url is not None:
            self.signalk_socket = SignalKPublisher(args.signalk_websocket_url)
        

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

    def parse_arguments(self):
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
            default="ws://localhost:3000/signalk/v1/stream?subscribe=none",
        )
        
        parser.add_argument(
            "-d",
            "--debug",
            action="store_true",
            help="sets the log level to debug",
        )

        parser.add_argument(
            "--skip-ble",
            action="store_true",
            help="Skip connecting to the BLE device for testing/debugging"
        )

        return parser.parse_args()

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


if __name__ == "__main__":
    asyncio.run(VesselViewMobileDataRecorder().main())


