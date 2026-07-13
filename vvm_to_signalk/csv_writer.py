"""Outputs data in CSV format to storage"""
import asyncio
import csv
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class CsvWriter:
    """CSV writer class accepts data parameters and periodically writes the current values out to CSV output"""

    def __init__(self, config: 'CsvWriterConfig'):
        self.__config = config
        self.__data = {}
        self.__timer = None
        self.__writer = None
        self.__flush_interval = config.flush_interval
        self.__fieldnames = None
        self.__wrote_fieldnames = False
        self.__output_stream = None
        self.__writer = None

    def update_active_items(self, item_ids: list[int]) -> None:
        """Part of the receiver interface; CSV columns are discovered lazily on first flush."""

    async def accept_fault(self, fault) -> None:
        """No-op: CSV writer does not record fault notifications."""

    async def accept_engine_identity(self, engine_id: int, kind: str, value: str) -> None:
        """No-op: CSV writer does not record engine identity strings."""

    async def accept_engine_data(self, item, engine_id: int, value) -> None:
        """Record one engine's latest value and schedule a flush."""
        if not self.__config.enabled:
            return
        self.__data[self.key_for(item, engine_id)] = value
        self.__data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.__timer is None:
            self.__timer = asyncio.create_task(self._flush_timer_task())

    @staticmethod
    def key_for(item, engine_id: int) -> str:
        """Column key for an engine's data item."""
        return f"{engine_id}_{item.name}"

    def _ensure_writer(self) -> bool:
        """Open the file and write the header from the keys seen so far (once)."""
        if self.__wrote_fieldnames:
            return True
        if not self.__config.enabled:
            return False
        keys = sorted(k for k in self.__data if k != "timestamp")
        if not keys:
            return False
        self.__fieldnames = ["timestamp"] + keys
        try:
            self.__output_stream = open(self.__config.filename, "a", newline="", encoding="utf-8")
            self.__writer = csv.DictWriter(self.__output_stream, fieldnames=self.__fieldnames,
                                           extrasaction="ignore")
            self.__writer.writeheader()
            self.__wrote_fieldnames = True
            return True
        except OSError as err:
            logger.warning("Unable to open CSV output file: %s", err)
            self.__config.enabled = False
            return False

    async def _flush_timer_task(self):
        """Wait for the flush interval then write a row."""
        await asyncio.sleep(self.__flush_interval)
        await self.flush_queue_to_csv()
        self.__timer = None

    async def flush_queue_to_csv(self):
        """Write the current row to the CSV file."""
        if not self._ensure_writer():
            return
        self.__writer.writerow(self.__data)
        self.__output_stream.flush()

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        if self.__output_stream is not None:
            self.__output_stream.close()


class CsvWriterConfig:

    """Configuration settings for the CSV Writer"""
    def __init__(self, data=None):
        self.__enabled = False
        self.__filename = "./logs/data.csv"
        self.__flush_interval = 1.0
        if data is not None:
            self.read(data)

    def read(self, data: dict):
        """Loads settings from a dictionary"""
        self.__enabled = data.get("enabled", self.__enabled)
        self.__filename = data.get("filename", self.__filename)
        self.__flush_interval = data.get("interval", self.__flush_interval)

    @property
    def enabled(self):
        """Enable output of data logging to CSV"""
        return self.__enabled

    @enabled.setter
    def enabled(self, value):
        self.__enabled = value

    @property
    def filename(self):
        """CSV output file"""
        return self.__filename

    @filename.setter
    def filename(self, value):
        self.__filename = value

    @property
    def flush_interval(self):
        """Minimum amount of time in seconds between updates to the CSV file"""
        return self.__flush_interval

    @flush_interval.setter
    def flush_interval(self, value):
        self.__flush_interval = value

    @property
    def valid(self):
        """Validate the configuration"""
        return (not self.__enabled or self.__filename is not None) and self.__flush_interval > 0
