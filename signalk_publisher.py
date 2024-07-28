import asyncio
import websockets
import json
import logging
import uuid

logger = logging.getLogger(__name__)

class SignalKPublisher:
    def __init__(self, webhook_url, username, password):
        self.webhook_url = webhook_url
        self.websocket = None
        self.socket_connected = False
        self.abort = False
        self.reconnect_interval_seconds = 30
        self.username = username
        self.password = password

    async def connect_websocket(self):
        """Connect to the Signal K server using a websocket."""
        logger.info("Connecting to SignalK: %s", self.webhook_url)
        user_agent_string = "bluetooth_to_signalk/1.0"
        try:
            self.websocket = await websockets.connect(self.webhook_url,
                                                      logger=logger,
                                                      user_agent_header=user_agent_string
                                                      )
            self.socket_connected = True
        except OSError:  # TCP connection fails
            logger.warn("Unable to connect to server: %s", self.webhook_url)
            self.socket_connected = False
        except websockets.exceptions.InvalidURI:
            logger.error("Invalid URI: %s", self.webhook_url)
            self.socket_connected = False
        except websockets.exceptions.InvalidHandshake:
            logger.error("Websocket service error. Check that the service is running and working properly.")
            self.socket_connected = False
        except TimeoutError:
            logger.warn("Websocket connection timed out.")
            self.socket_connected = False
        return self.socket_connected
            
    def socket_connected(self):
        return self.socket_connected
    
    async def close(self):
        logger.info("Closing websocket...")
        if self.socket_connected:
            self.abort = True
            await self.websocket.close()
            self.socket_connected = False
        logger.info("Websocket closed.")

    async def run(self, task_group):
        while not self.abort:
            await self.connect_websocket()
            while not self.socket_connected:
                logger.warn("Unable to connect to signalk websocket. Will retry...")
                await asyncio.sleep(self.reconnect_interval_seconds)
                await self.connect_websocket()
            
            logger.info("Connected to signalk websocket %s", self.webhook_url)
        
            # authenticate
            if self.username is not None:
                await self.authenticate(self.username, self.password)

            # receive messages
            while self.socket_connected:
                try:
                    msg = await self.websocket.recv()
                    if msg is not None:
                        self.process_webhook_message(msg)                    
                except websockets.exceptions.ConnectionClosedError:
                    logger.error("Websocket connection was closed - need to reset connection.")
                    self.socket_connected = False

    def process_webhook_message(self, msg):
        logger.info("SignalK webhook received: %s", msg)

    async def authenticate(self, username, password):
        data = { 
            "requestId": self.generate_request_id(),
            "login": {
                "username": username,
                "password": password
            }
        }
        await self.websocket.send(json.dumps(data))

    def generate_request_id(self):
        return str(uuid.uuid4())

    def generate_delta(self, path, value):
        delta = {
            "requestId": self.generate_request_id(),
            "context": "vessels.self",
            "updates": [
                {
                    "values": [
                        {
                            "path": path,
                            "value": value
                        }
                    ]
                }
            ]
        }
        return delta

    async def publish_delta(self, path, value):
        logger.debug(f"Received delta to publish: '{path}', value '{value}'")        
        
        if self.socket_connected:
            delta = self.generate_delta(path, value)
            try:
                await self.websocket.send(json.dumps(delta))
            except websockets.exceptions.ConnectionClosed:
                logger.warn(f"Websocket connection closed. Data delta may not have been published.")
        else:
            logger.warn(f"Websocket connection closed. No data was sent.")




