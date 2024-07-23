
import asyncio
import websockets
import requests
import json

# uri = "ws://localhost:3000/signalk/v1/stream?subscribe=none"

class SignalKClient:
    def __init__(self, webhook_url, api_url):
        self.webhook_url = webhook_url
        self.api_url = api_url
        self.callbacks = []
        self.websocket = None

    def add_callback(self, callback):
        """Adds a callback to be called when new data is received."""
        self.callbacks.append(callback)

    async def connect_websocket(self):
        """Connect to the Signal K server using a websocket."""
        self.websocket = websockets.connect(self.webhook_url)
        async with websockets.connect(self.webhook_url) as websocket:
            while True:
                data = await websocket.recv()
                self.handle_data(data)

    def handle_data(self, data):
        """Handles incoming data and calls the registered callbacks."""
        try:
            json_data = json.loads(data)
            for callback in self.callbacks:
                callback(json_data['path'], json_data['value'])
        except (KeyError, json.JSONDecodeError) as e:
            print(f"Error handling data: {e}")

    def start(self):
        """Start the websocket connection."""
        asyncio.get_event_loop().run_until_complete(self.connect_websocket())


    

    def publish_delta(self, path, value):
            """Publish a new delta to the Signal K server."""
            delta = {
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
            headers = {'Content-Type': 'application/json'}
            try:
                response = requests.post(self.api_url, data=json.dumps(delta), headers=headers)
                response.raise_for_status()
                print(f"Successfully published delta: {delta}")
            except requests.exceptions.RequestException as e:
                print(f"Failed to publish delta: {e}")


