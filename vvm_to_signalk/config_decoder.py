"""Configuration module"""

import logging
from collections.abc import Iterable
from typing import Protocol

logger = logging.getLogger(__name__)

class ConfigDecoder:
    """Decodes saved configuration data into objects"""
    def __init__(self):
        self.__known_data = []  # array of byte arrays
        self.__has_all_data = None
        self.__active_ids = []

    def add(self, item):
        """Adds a new data packet to the decoder"""
        if isinstance(item, Iterable) and not isinstance(item, (str, bytes)):
            self.__known_data.extend(item)
        else:
            self.__known_data.append(item)
        self.__has_all_data = None

    @property
    def has_all_data(self):
        """Indicates the configuration has all the data required"""
        if self.__has_all_data is None:
            try:
                self.combine_and_parse_data()
            except ValueError:
                pass

        return self.__has_all_data

    @has_all_data.setter
    def has_all_data(self, value):
        self.__has_all_data = value

    def active_data_item_ids(self) -> list[int]:
        """Data-item IDs the device will stream, in slot order (zero slots dropped)."""
        if self.__has_all_data is None:
            self.has_all_data  # trigger parse
        return self.__active_ids

    def combine_and_parse_data(self) -> list[int]:
        """Combine data received from the device into one package"""

        # sort known_data by the first byte
        data = self.__known_data
        logger.debug("Starting data: %s", data)

        sorted_data = sorted(data, key=lambda x: x[0])
        logger.debug("Sorted data: %s", sorted_data)

        # drop the first byte of each packet
        clean_data = [byte_array[1:] for byte_array in sorted_data]

        # combine the known data into a single byte stream
        combined = b''.join(clean_data)
        logger.debug("Combined data: %s", combined.hex())

        return self.parse_params(combined)

    def parse_params(self, combined_data) -> list[int]:
        """Parse parameters to make sure they are valid"""

        # check to see if we have a valid header on the data
        if not combined_data:
            self.has_all_data = None
            raise ValueError("No data to parse.")

        if combined_data[0] != 0x28:
            logger.warning("Unexpected data format - value doesn't start with 0x28: %s", combined_data.hex())
            self.has_all_data = False
            raise ValueError("Value of first byte is not expected value.")

        # check to see if we have all the data we expect
        length_of_data = int.from_bytes(combined_data[1:2], byteorder='little')
        actual_length = len(combined_data[3:])
        logger.debug("Expected data length %s, actual %s", length_of_data, actual_length)
        if actual_length != length_of_data:
            self.has_all_data = False
            raise ValueError(f"Expected {length_of_data} bytes, but only have {actual_length}.")

        # parse the data into active data-item IDs
        magic_number, parsing_data = ConfigDecoder.pop_bytes(combined_data[3:], 2)
        logger.debug("Magic number was %s", magic_number.hex())
        found_ids = []
        while len(parsing_data) != 0:
            next_pair, parsing_data = ConfigDecoder.pop_bytes(parsing_data, 4)
            # bytes 0-1 = slot index, bytes 2-3 = data-item id (little-endian)
            data_item_id = int.from_bytes(next_pair[2:4], byteorder="little")
            if data_item_id != 0:
                found_ids.append(data_item_id)
            remaining_bytes = len(parsing_data)
            if 0 < remaining_bytes < 4:
                logger.debug("Remaining bytes (%s) indicate incomplete data.", remaining_bytes)
                self.has_all_data = False
                raise ValueError("Incorrect data length.")

        self.__active_ids = found_ids
        self.has_all_data = True
        return found_ids

    @staticmethod
    def pop_bytes(byte_array, num_bytes):
        """Pops a count of bytes off the begining of an array"""
        # Extract the first num_bytes
        popped_bytes = byte_array[:num_bytes]
        # Update the original byte array by removing the popped bytes
        remaining_bytes = byte_array[num_bytes:]
        return popped_bytes, remaining_bytes


# pylint: disable=missing-function-docstring
class EngineDataReceiver(Protocol):
    """Protocol for classes that can receive decoded engine data."""
    async def accept_engine_data(self, item, engine_id: int, value: float) -> None:
        ...

    async def accept_fault(self, fault) -> None:
        ...

    async def accept_engine_identity(self, engine_id: int, kind: str, value: str) -> None:
        ...

    def update_active_items(self, item_ids: list[int]) -> None:
        ...
