"""Module for SignalK data processing"""

import json
import logging
import uuid
import asyncio
import websockets

from .futures_queue import FuturesQueue
from .signalk_mapping import signalk_path, to_si, engine_label, _camel
from .notification_policy import method_for, state_for

_OFFLINE_FAULT_IDS = {87, 106}     # enum-style single alarm (Guardian Cause, MIL)
_BITFIELD_FAULT_IDS = {97}         # one notification per bit (Seven Function Gauge)
_GUARDIAN_CAUSE_ID = 87            # enum path: distinguishes Guardian (87) from MIL (106)

logger = logging.getLogger(__name__)

class SignalKPublisher:
    """Class for publishing data to SignalK API"""

    def __init__(self, config: 'SignalKConfig', health_status):
        self.__config = config

        self.__websocket = None
        self.__socket_connected = False
        self.__abort = False
        self.__notifications = FuturesQueue()
        self.__health = health_status
        self.__should_log_connection_down = True
        self.__last_notification_state = {}

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
        """Indicates connection status to SignalK API"""
        return self.__socket_connected
    
    @socket_connected.setter
    def socket_connected(self, value):
        self.__socket_connected = value

    def set_health(self, value: bool, message: str = None):
        """Sets the health of the SignalK connection"""
        self.__health["signalk"] = value
        if message is None:
            self.__health.pop("signalk_error", None)
        else:
            self.__health["signalk_error"] = message
            logger.info(message)

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
                try:
                    # Check to see if the response was successful
                    if response_json.get("statusCode") == 200:
                        logger.info("authenticated with singalk successfully")
                        self.__auth_token = response_json.get("login", {}).get("token")
                    else:
                        logger.critical("Unable to authenticate with SignalK server. Username or password may be incorrect. Response: %s", response_json)
                except Exception as e:
                    logger.critical("Error processing authentication response: %s. Response: %s", e, response_json)

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
                    "source": { "label": "vvm_monitor" },
                    "values": [{"path": path, "value": value}]
                }
            ]
        }
        return delta
    
    def update_active_items(self, item_ids):
        """No-op: the publisher maps each value as it arrives."""

    async def _send_notification(self, path, state, message, extra=None):
        """Send a SignalK notification delta, but only when the state changed since
        the last published value for this path (avoids per-cycle notification spam)."""
        if self.__last_notification_state.get(path) == state:
            return
        if not self.socket_connected:
            return
        value = {"state": state,
                 "method": method_for(state),
                 "message": message}
        if extra:
            value["vvm"] = extra
        try:
            await self.__websocket.send(json.dumps(self.generate_delta(path, value)))
            self.__last_notification_state[path] = state
        except Exception as e:
            logger.warning("Error sending notification: %s", e)

    async def accept_engine_data(self, item, engine_id, value) -> None:
        """Publish a decoded engine value as a SignalK delta."""
        label = engine_label(engine_id, self.__config.engine_labels)
        if item.id in _OFFLINE_FAULT_IDS:
            text = item.render_enum(value) or str(int(value))
            is_active = int(value) != 0  # 0 == GC_NONE / MIL Off
            kind = "guardian" if item.id == _GUARDIAN_CAUSE_ID else "mil"
            await self._send_notification(
                f"notifications.propulsion.{label}.{_camel(item.name)}",
                state_for(kind, text, is_active),
                f"Engine {engine_id} {item.name}: {text}")
            return
        if item.id in _BITFIELD_FAULT_IDS:
            for flag_name, flag_val in item.render_bits(value).items():
                await self._send_notification(
                    f"notifications.propulsion.{label}.{_camel(flag_name)}",
                    state_for("bitfield", flag_name, bool(flag_val)),
                    f"Engine {engine_id} {flag_name}: {'active' if flag_val else 'clear'}")
            return
        path = signalk_path(item, engine_id, self.__config.engine_labels,
                            include_unmapped=self.__config.send_unknown_parameters)
        if path is None:
            logger.debug("No SignalK path for %s; skipping", item.name)
            return
        si_value = to_si(value, item.units)
        if self.socket_connected:
            delta = self.generate_delta(path, si_value)
            try:
                await self.__websocket.send(json.dumps(delta))
                self.__should_log_connection_down = True
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Websocket closed; delta not published.")
            except Exception as e:
                logger.warning("Error sending on websocket: %s", e)

    async def accept_fault(self, fault):
        """Publish a fault as a SignalK notification delta."""
        label = engine_label(fault.engine_position, self.__config.engine_labels)
        path = f"notifications.propulsion.{label}.vvmFault.{fault.fault_key}"
        description = fault.description
        message = f"Engine {fault.engine_position} fault {fault.fault_key}"
        if description:
            message += f": {description}"
        if not fault.is_active:
            message += " cleared"
        value = {
            "state": "alarm" if fault.is_active else "normal",
            "method": ["visual", "sound"] if fault.is_active else [],
            "message": message,
            "vvm": {
                "faultId": fault.fault_id,
                "failureTypeId": fault.failure_type_id,
                "severity": fault.severity,
                "type": fault.fault_type,
                "description": description,
            },
        }
        if self.socket_connected:
            try:
                await self.__websocket.send(json.dumps(self.generate_delta(path, value)))
            except Exception as e:
                logger.warning("Error sending fault on websocket: %s", e)

    async def accept_engine_identity(self, engine_id, kind, value):
        """Publish an engine identity string (Software/Calibration/Serial/ECU IDs)
        as a SignalK metadata delta at propulsion.<label>.vvm.<kind>."""
        label = engine_label(engine_id, self.__config.engine_labels)
        path = f"propulsion.{label}.vvm.{kind}"
        if self.socket_connected:
            try:
                await self.__websocket.send(json.dumps(self.generate_delta(path, value)))
            except Exception as e:
                logger.warning("Error sending engine identity on websocket: %s", e)


class SignalKConfig:
    """Defines the configuration for the SignalK server"""
    def __init__(self, data: dict = None):
        self.__websocket_url = None
        self.__username = None
        self.__password = None
        self.__retry_interval = 5
        self.__send_unknown_parameters = False
        self.__engine_labels = None
        if data is not None:
            self.read(data)
    
    def read(self, data: dict):
        """Reads configuration from a dictionary"""
        if data is None:
            return
        self.__websocket_url = data.get('websocket-url', self.__websocket_url)
        self.__username = data.get('username', self.__username)
        self.__password = data.get('password', self.__password)
        self.__retry_interval = data.get('retry-interval-seconds', self.__retry_interval)
        self.__send_unknown_parameters = data.get('send-unknown-parameters', self.__send_unknown_parameters)
        labels = data.get('engine-labels')
        if labels is not None:
            self.__engine_labels = {int(k): str(v) for k, v in labels.items()}

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
    
    @property
    def send_unknown_parameters(self):
        """Option to skip exporting unknown values to signal k"""
        return self.__send_unknown_parameters
    
    @send_unknown_parameters.setter
    def send_unknown_parameters(self, value):
        self.__send_unknown_parameters = value

    @property
    def engine_labels(self):
        """Optional dict mapping engine_id -> label string."""
        return self.__engine_labels

    @engine_labels.setter
    def engine_labels(self, value):
        self.__engine_labels = value
