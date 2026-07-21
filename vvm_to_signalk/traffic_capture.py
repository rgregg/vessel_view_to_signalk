"""Append-only capture of relayed BLE proxy traffic."""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class TrafficCapture:
    """Records every relayed GATT operation as one timestamped hex line."""

    def __init__(self, path: str, enabled: bool = True):
        self._enabled = enabled
        self._path = path
        self._fh = None
        if self._enabled:
            self._fh = open(path, "a", encoding="utf-8")  # noqa: SIM115

    def record(self, direction: str, operation: str, uuid: str, data: bytes,
               now: datetime | None = None) -> None:
        """Append one capture line. No-op when disabled."""
        if not self._enabled or self._fh is None:
            return
        ts = (now or datetime.now(timezone.utc)).isoformat()
        self._fh.write(f"{ts} {direction} {operation} {uuid} {data.hex()}\n")
        self._fh.flush()

    def close(self) -> None:
        """Close the capture file."""
        if self._fh is not None:
            self._fh.close()
            self._fh = None
