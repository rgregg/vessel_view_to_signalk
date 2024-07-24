import asyncio
import websockets
import json
import logging
import uuid

logger = logging.getLogger(__name__)

class SignalKClient:
    def __init__(self, webhook_url):
        self.webhook_url = webhook_url
        self.websocket = None

    async def connect_websocket(self):
        """Connect to the Signal K server using a websocket."""
        logger.info("Connecting to SignalK: %s", self.webhook_url)
        self.websocket = await websockets.connect(self.webhook_url)

    async def run(self, task_group):
        await self.connect_websocket()
        logger.info("Connected to websocket")
        
        while True:
            msg = await self.websocket.recv()
            logger.debug("WS RECV: %s", msg)
            # Perform some task if condition is met

    async def authenticate(self, username, password):
        data = { 
            "requestId": self.generate_request_id(),
            "login": {
                "username": username,
                "password": password
            }
        }
        await self.websocket.send(json.dumps(data))

    def handle_data(self, data):
        """Handles incoming data and calls the registered callbacks."""
        try:
            json_data = json.loads(data)
            for callback in self.callbacks:
                callback(json_data['path'], json_data['value'])
        except (KeyError, json.JSONDecodeError) as e:
            logger.error(f"Error handling data: {e}")

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
        logger.info(f"Publishing delta: {value} to {path}")
        delta = self.generate_delta(path, value)
        await self.websocket.send(json.dumps(delta))




