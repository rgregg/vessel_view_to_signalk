"""Module for SignalK data processing"""

import json
import logging
import uuid
import asyncio
import websockets
from .futures_queue import FuturesQueue

logger = logging.getLogger(__name__)

class SignalKPublisher:
    """Class for publishing data to SignalK API"""

    def __init__(self, config: 'SignalKConfig', health_status):
        self.__config = config
        
        self.__websocket = None
        self.__socket_connected = False
        self.__abort = False
        self.__notifications = FuturesQueue()
        self.__auth_token = None
        self.__task_group = None
        self.__health = health_status

    @property
    def websocket_url(self):
        """URL for the SignalK websocket"""
        return self.__config.websocket_url
    
    @property
    def username(self):
        """Username for authenticating with SignalK"""
        return self.__config.username
    
    @property
    def password(self):
        """Password for authenticating with SignalK"""
        return self.__config.password
    
    @property
    def retry_interval_seconds(self):
        """Interval in seconds the system will return the connection
        if it fails"""
        return self.__config.retry_interval
    
    @property
    def socket_connected(self):
        """Indicates conncetion status to SignalK API"""
        return self.__socket_connected
    
    @socket_connected.setter
    def socket_connected(self, value):
        self.__socket_connected = value

    def set_health(self, value: bool, message: str = None):
        """Sets the health of the SignalK connection"""
        self.__health["signalk"] = value
        if message is None:
            del self.__health["signalk_error"]
        else:
            self.__health["signalk_error"] = message
            logger.warning(message)
        


    async def connect_websocket(self):
        """Connect to the Signal K server using a websocket."""
        logger.info("Connecting to SignalK: %s", self.websocket_url)
        user_agent_string = "vvmble_to_signalk/1.0"
        try:
            self.__websocket = await websockets.connect(self.websocket_url,
                                                      logger=logger,
                                                      user_agent_header=user_agent_string
                                                      )
            self.set_health(True)
            self.socket_connected = True
        except TimeoutError:
            self.set_health(False, "Websocket connection timed out.")
            self.socket_connected = False
        except OSError as e:  # TCP connection fails
            self.set_health(False, f"Connection failed to '{self.websocket_url}': {e}")
            self.socket_connected = False
        except websockets.exceptions.InvalidURI:
            self.set_health(False, f"Invalid URI: {self.websocket_url}")
            self.socket_connected = False
        except websockets.exceptions.InvalidHandshake:
            self.set_health(False, "Websocket service error. Check that the service is running and working properly.")        
            self.socket_connected = False
        return self.socket_connected
                
    async def close(self):
        """Closes the connection to SignalK API"""
        logger.info("Closing websocket...")
        if self.socket_connected:
            self.__abort = True
            await self.__websocket.close()
            self.set_health(False, "websocket closed")
            self.socket_connected = False
            
        logger.info("Websocket closed.")

    async def run(self, task_group):
        """Starts a run loop for the SignalK websocket"""

        self.__task_group = task_group
        while not self.__abort:
            await self.connect_websocket()
            while not self.socket_connected:
                logger.warning("Unable to connect to signalk websocket. Will retry...")
                await asyncio.sleep(self.retry_interval_seconds)
                await self.connect_websocket()
            
            logger.info("Connected to signalk websocket %s", self.websocket_url)
        
            # authenticate
            if self.username is not None:
                await self.authenticate(self.username, self.password)

            # receive messages
            while self.socket_connected:
                try:
                    if (msg := await self.__websocket.recv()) is not None:
                        self.process_websocket_message(msg)                    
                except (websockets.exceptions.ConnectionClosedOK, websockets.exceptions.ConnectionClosedError) as e:
                    self.set_health(False, f"websocket connection was closed: {e}")
                    self.socket_connected = False

    def process_websocket_message(self, msg):
        """Process a received message from the websocket"""

        logger.debug("Websocket message received: %s", msg)
        data = json.loads(msg)
        if "requestId" in data:
            request_id = data["requestId"]
            self.__notifications.trigger(request_id, data)
        else:
            logger.debug("No request ID was in received websocket message: %s", msg)

    async def authenticate(self, username, password):
        """Authenticate with the SignalK server via websocket"""
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
            logger.debug("response_json: %s", response_json)
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
        """Generate a new require ID (UUID)"""
        return str(uuid.uuid4())

    def generate_delta(self, path, value):
        """Generates a delta message for SignalK based on a path and value"""
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
        """Publishes a delta to the SignalK API"""
        logger.debug("Received delta to publish: '%s', value '%s'", path, value)
        if self.socket_connected:
            delta = self.generate_delta(path, value)
            try:
                await self.__websocket.send(json.dumps(delta))
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Websocket connection closed. Data delta may not have been published.")
            except Exception as e:
                logger.warning("Error sending on websocket: %s", e)
        else:
            logger.warning("Websocket connection closed. No data was sent.")

class SignalKConfig:
    """Defines the configuration for the SignalK server"""
    def __init__(self):
        self.__websocket_url = None
        self.__username = None
        self.__password = None
        self.__retry_interval = 30

    @property
    def websocket_url(self):
        """URL for the SignalK Websocket"""
        return self.__websocket_url
    
    @websocket_url.setter
    def websocket_url(self, value):
        self.__websocket_url = value

    @property
    def username(self):
        """Username for authenticating with SignalK"""
        return self.__username
    
    @username.setter
    def username(self, value):
        self.__username = value

    @property
    def password(self):
        """Password for authenticating with SignalK"""
        return self.__password
    
    @password.setter
    def password(self, value):
        self.__password = value

    @property
    def retry_interval(self):
        """Retry interval in seconds for connection to SignalK websocket"""
        return self.__retry_interval
    
    @retry_interval.setter
    def retry_interval(self, value):
        self.__retry_interval = value

    @property
    def valid(self):
        """Indicates if the configuration is valid with required parameters populated"""
        return self.__websocket_url is not None

