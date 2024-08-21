import logging
from enum import Enum
from collections.abc import Iterable

logger = logging.getLogger(__name__)


class ConfigDecoder:

    def __init__(self):
        self.__known_data = []  # array of byte arrays
        self.__has_all_data = None
        self.__parameters = []
    
    """
    Adds a new data packet to the decoder
    """
    def add(self, item):
        if isinstance(item, Iterable) and not isinstance(item, (str, bytes)):
            self.__known_data.extend(item)
        else:
            self.__known_data.append(item)
        self.__has_all_data = None

    @property
    def has_all_data(self):
        # check to see if we have all the data required
        if self.__has_all_data is None:
            self.parse_data()

        return self.__has_all_data
    
    @has_all_data.setter
    def has_all_data(self, value):
        self.__has_all_data = value

    @property
    def engine_parameters(self):
        return self.__parameters
    
    @engine_parameters.setter
    def engine_parameters(self, value):
        self.__parameters = value

    def parse_data(self):
        # sort known_data by the first byte
        data = self.__known_data
        logger.debug(f"Starting data: {data}")

        sorted_data = sorted(data, key=lambda x: x[0])
        logger.debug(f"Sorted data: {sorted_data}")

        # drop the first byte of each packet
        clean_data = [byte_array[1:] for byte_array in sorted_data]

        # combine the known data into a single byte stream
        combined = b''.join(clean_data)
        logger.debug(f"Combined data: {combined.hex()}")

        # check to see if we have a valid header on the data
        if combined[0] != 0x28:
            logger.error(f"Unexpected data format: {combined[0]}")
            self.has_all_data = False
            raise ValueError("Value of first byte is not expected value.")

        # check to see if we have all the data we expect
        length_of_data = int.from_bytes(combined[1:2], byteorder='little')
        test = combined[3:] # ignore header & length data
        actual_length = len(combined[3:])
        logger.debug(f"Expected data length {length_of_data}, actual {actual_length}")
        if actual_length != length_of_data:
            self.has_all_data = False
            raise ValueError(f"Expected {length_of_data} bytes, but only have {actual_length}.")

        # parse the data into output
        magic_number, parsing_data = ConfigDecoder.pop_bytes(combined[3:], 2)
        logger.debug(f"Magic number was {int.from_bytes(magic_number, byteorder='little')}")
        found_params = []
        while len(parsing_data) != 0:
            next_param, parsing_data = ConfigDecoder.pop_bytes(parsing_data, 4)
            param_id = int.from_bytes(next_param[:2])
            header_id = int.from_bytes(next_param[2:])
            found_params.append(EngineParameter(param_id, header_id))

            remaining_bytes = len(parsing_data)
            if remaining_bytes > 0 and remaining_bytes < 4:
                logger.debug(f"Remaining bytes ({remaining_bytes}) indicate the data is incomplete.")
                self.has_all_data = False
                raise ValueError("Incorrect data length.")

        self.engine_parameters = found_params
        self.has_all_data = True
        
        return found_params
        
    def pop_bytes(byte_array, num_bytes):
        # Extract the first num_bytes
        popped_bytes = byte_array[:num_bytes]
        # Update the original byte array by removing the popped bytes
        remaining_bytes = byte_array[num_bytes:]
        return popped_bytes, remaining_bytes


class EngineParameterType(Enum):
    ENGINE_RPM = 0
    COOLANT_TEMPERATURE = 1
    BATTERY_VOLTAGE = 2
    UNKNOWN_3 = 3
    ENGINE_RUNTIME = 4
    CURRENT_FUEL_FLOW = 5
    UNKNOWN_6 = 6
    UNKNOWN_7 = 7
    OIL_PRESSURE = 8
    UNKNOWN_9 = 9
    UNKNOWN_A = 10
    UNKNOWN_B = 11
    UNKNOWN_C = 12
    UNKNOWN_D = 13
    UNKNOWN_E = 14
    UNKNOWN_F = 15



class EngineParameter:

    def __init__(self, parameter: int, notification_header: int):
        self.__parameter_id = parameter
        self.__notification_header = notification_header
        self.__param_enabled = (notification_header != 0)
        self.__engine_id = parameter >> 8
        self.__parameter_type = EngineParameterType(parameter & 0xFF)

    @property
    def parameter_id(self):
        return self.__parameter_id
    
    @property
    def notification_header(self):
        return self.__notification_header

    @property
    def enabled(self):
        return self.__param_enabled
    
    @property
    def engine_id(self):
        return self.__engine_id
    
    @property
    def parameter_type(self):
        return self.__parameter_type
    
    @property
    def signalk_path(self):
        path = self.get_signalk_path()
        return f"propulsion.{self.engine_id}.{path}"
        
    def get_signalk_path(self):
        if self.parameter_type == EngineParameterType.ENGINE_RPM:
            return "revolutions"
        elif self.parameter_type == EngineParameterType.COOLANT_TEMPERATURE:
            return "temperature"
        elif self.parameter_type == EngineParameterType.BATTERY_VOLTAGE:
            return "alternatorVoltage"
        elif self.parameter_type == EngineParameterType.ENGINE_RUNTIME:
            return "runTime"
        elif self.parameter_type == EngineParameterType.CURRENT_FUEL_FLOW:
            return "fuel.rate"
        elif self.parameter_type == EngineParameterType.OIL_PRESSURE:
            return "oilPressure"
        else:
            logger.warning(f"Unable to map SignalK path for parameter type {self.parameter_type} on engine {self.engine_id}.")
            return self.parameter_type.name

    
