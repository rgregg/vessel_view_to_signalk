"""Decode VVM Fault Alert (0x201) indications. See docs/protocol-map.md §3."""
import logging
from collections import namedtuple

logger = logging.getLogger(__name__)

_FAULT_TYPES = {0: "Unknown", 1: "Universal", 2: "Legacy"}

FaultText = namedtuple("FaultText", ["title", "advisory"])

# Offline fault text recorded from the native SmartCraft app. Mercury resolves
# fault text through a cloud API (protocol-map.md §3.5) with no offline
# dictionary, so this is a hand-maintained map of Universal codes keyed by
# `fault_key` = "<fault_id>-<failure_type_id>". `title` is shown in the
# notification message; `advisory` (the app's actionable Line-3 text) is carried
# in the SignalK vvm block and is None when the app shows none. Unknown codes
# fall back to the bare key.
FAULT_TEXT = {
    "946-6": FaultText("Catalyst oxygen storage capacity (starboard)", None),
    "1104-21": FaultText(
        "Drive lube",
        "Drive lube is low. Continued operation may cause damage."),
    "3151-16": FaultText(
        "Malfunction indicator lamp",
        "Malfunction indicator lamp is not working properly."),
    "1109-23": FaultText(
        "Emergency stop",
        "Check lanyard - key engine off and restart. If condition persists, "
        "service engine soon."),
    "4602-23": FaultText(
        "Fault blocker system voltage",
        "Return to port immediately - turn off unnecessary loads and check "
        "battery connections. Service engine before next use."),
    "3061-16": FaultText(
        "Fuel pump",
        "Fuel pump is not working properly. Return to port immediately - "
        "service engine before next use."),
    "842-16": FaultText(
        "Wideband O2 sensor heater - starboard bank (S1)",
        "Exhaust oxygen sensor is not working properly."),
    "822-16": FaultText(
        "Wideband O2 sensor heater - port bank (S1)",
        "Exhaust oxygen sensor is not working properly."),
}


class Fault:
    """A decoded engine fault event."""

    def __init__(self, fault_type, engine_position, is_active, fault_id,
                 failure_type_id=None, severity=None, action_id=None):
        self.fault_type = fault_type
        self.engine_position = engine_position
        self.is_active = is_active
        self.fault_id = fault_id
        self.failure_type_id = failure_type_id
        self.severity = severity
        self.action_id = action_id

    def __str__(self):
        desc = self.description
        desc_part = f', desc="{desc}"' if desc else ""
        return (f"Fault(type={self.fault_type}, engine={self.engine_position}, "
                f"active={self.is_active}, key={self.fault_key}{desc_part})")

    @property
    def fault_key(self) -> str:
        if self.fault_type == "Universal":
            return f"{self.fault_id}-{self.failure_type_id}"
        return f"{self.fault_id}-Legacy"

    @property
    def description(self) -> str | None:
        """Title text for this fault code, or None if not in FAULT_TEXT."""
        entry = FAULT_TEXT.get(self.fault_key)
        return entry.title if entry else None

    @property
    def advisory(self) -> str | None:
        """Actionable advisory text for this fault code, or None."""
        entry = FAULT_TEXT.get(self.fault_key)
        return entry.advisory if entry else None


def _common_header(data: bytes):
    fault_type = _FAULT_TYPES.get(data[0] & 0x0F, "Unknown")
    engine_position = data[0] >> 4
    is_active = bool(data[1] & 0x01)
    return fault_type, engine_position, is_active


def parse_fault(data: bytes) -> Fault | None:
    """Parse a Fault Alert payload (4 bytes = Legacy, 9 bytes = Universal)."""
    if data is None:
        return None
    if len(data) == 4:
        fault_type, engine, active = _common_header(data)
        fault_id = int.from_bytes(data[2:4], byteorder="little")
        return Fault(fault_type, engine, active, fault_id)
    if len(data) == 9:
        fault_type, engine, active = _common_header(data)
        body = data[2:9].ljust(8, b"\x00")
        num = int.from_bytes(body, byteorder="little")
        severity = num & 0x7
        action_id = (num & 0xFF8) >> 3
        # long_id = (num & 0x7FF000) >> 12  # not currently published
        # short_id = (num & 0x7FF800000) >> 23
        failure_type_id = (num & 0x3F800000000) >> 35
        fault_id = (num & 0xFFFC0000000000) >> 42
        return Fault(fault_type, engine, active, fault_id,
                     failure_type_id=failure_type_id, severity=severity, action_id=action_id)
    logger.warning("Unexpected fault payload length %s: %s", len(data), data.hex())
    return None
