import asyncio
import websockets
import json
import logging
import uuid
from futures_queue import FuturesQueue

logger = logging.getLogger(__name__)

class SignalKPublisher:
    def __init__(self, config: 'SignalKConfig'):
        self.__config = config
        
        self.__websocket = None
        self.__socket_connected = False
        self.__abort = False
        self.__notifications = FuturesQueue()
        self.__auth_token = None

    @property
    def websocket_url(self):
        return self.__config.websocket_url
    
    @property
    def username(self):
        return self.__config.username
    
    @property
    def password(self):
        return self.__config.password
    
    @property
    def retry_interval_seconds(self):
        return self.__config.retry_interval
    
    @property
    def socket_connected(self):
        return self.__socket_connected
    
    @socket_connected.setter
    def socket_connected(self, value):
        self.__socket_connected = value

    async def connect_websocket(self):
        """Connect to the Signal K server using a websocket."""
        logger.info("Connecting to SignalK: %s", self.websocket_url)
        user_agent_string = "vvmble_to_signalk/1.0"
        try:
            self.__websocket = await websockets.connect(self.websocket_url,
                                                      logger=logger,
                                                      user_agent_header=user_agent_string
                                                      )
            self.socket_connected = True
        except OSError:  # TCP connection fails
            logger.warn("Unable to connect to server: %s", self.websocket_url)
            self.socket_connected = False
        except websockets.exceptions.InvalidURI:
            logger.error("Invalid URI: %s", self.websocket_url)
            self.socket_connected = False
        except websockets.exceptions.InvalidHandshake:
            logger.error("Websocket service error. Check that the service is running and working properly.")
            self.socket_connected = False
        except TimeoutError:
            logger.warn("Websocket connection timed out.")
            self.socket_connected = False
        return self.socket_connected
                
    async def close(self):
        logger.info("Closing websocket...")
        if self.socket_connected:
            self.__abort = True
            await self.__websocket.close()
            self.socket_connected = False
        logger.info("Websocket closed.")

    async def run(self, task_group):
        while not self.__abort:
            await self.connect_websocket()
            while not self.socket_connected:
                logger.warn("Unable to connect to signalk websocket. Will retry...")
                await asyncio.sleep(self.reconnect_interval_seconds)
                await self.connect_websocket()
            
            logger.info("Connected to signalk websocket %s", self.websocket_url)
        
            # authenticate
            if self.username is not None:
                await self.authenticate(self.username, self.password)

            # receive messages
            while self.socket_connected:
                try:
                    msg = await self.__websocket.recv()
                    if msg is not None:
                        self.process_websocket_message(msg)                    
                except (websockets.exceptions.ConnectionClosedOK, websockets.exceptions.ConnectionClosedError) as e:
                    logger.error(f"Websocket connection was closed: {e}.")
                    self.socket_connected = False

    def process_websocket_message(self, msg):
        logger.debug("Websocket message received: %s", msg)
        try:
            data = json.loads(msg)
            if "requestId" in data:
                request_id = data["requestId"]
                self.__notifications.trigger(request_id, data)
            else:
                logger.debug(f"No request ID was in received websocket message: {msg}")
        except Exception as e:
            raise
            logger.warning(f"Error parsing websocket message: {e}")

    async def authenticate(self, username, password):
        logger.info("Authenticating with websocket...")

        login_request = self.generate_request_id()
        data = { 
            "requestId": login_request,
            "login": {
                "username": username,
                "password": password
            }
        }

        def process_login(future):
            response_json = future.result()
            logger.debug(f"response_json: {response_json}")
            if response_json is not None:
                # Check to see if the response was successful
                if response_json["statusCode"] == 200:
                    logger.info("authenticated with singalk successfully")
                    self.__auth_token = response_json["login"]["token"]
                else:
                    logger.critical("Unable to authenticate with SignalK server. Username or password may be incorrect.")

        self.__notifications.register_callback(login_request, process_login)
        await self.__websocket.send(json.dumps(data))
        

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
                await self.__websocket.send(json.dumps(delta))
            except websockets.exceptions.ConnectionClosed:
                logger.warn(f"Websocket connection closed. Data delta may not have been published.")
            except Exception as e:
                logger.warn(f"Error sending on websocket: {e}")
        else:
            logger.warn(f"Websocket connection closed. No data was sent.")

class SignalKConfig:
    def __init__(self):
        self.__websocket_url = None
        self.__username = None
        self.__password = None
        self.__retry_interval = 30

    @property
    def websocket_url(self):
        return self.__websocket_url
    
    @websocket_url.setter
    def websocket_url(self, value):
        self.__websocket_url = value

    @property
    def username(self):
        return self.__username
    
    @username.setter
    def username(self, value):
        self.__username = value

    @property
    def password(self):
        return self.__password
    
    @password.setter
    def password(self, value):
        self.__password = value

    @property
    def retry_interval(self):
        return self.__retry_interval
    
    @retry_interval.setter
    def retry_interval(self, value):
        self.__retry_interval = value

    @property
    def valid(self):
        return self.__websocket_url is not None

