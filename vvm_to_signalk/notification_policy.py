"""Notification policy: decide a SignalK notification's ``state`` (and hence
whether it is an audible alarm or a silent visual notice) for VVM conditions.

Quiet by default: an active condition is a silent ``alert`` unless it appears on
a curated critical allowlist, in which case it is an audible ``alarm``. Cleared
conditions are ``normal``.

The opaque 0-7 Universal-fault severity integer is deliberately NOT consulted;
its meaning is cloud-resolved and unknown to this codebase. Policy keys off
identifiers we understand (Guardian Cause enum text, Seven-Function Gauge flag
names, and fault keys).
"""

# Single source of truth for how a state renders as a SignalK notification
# method. Clients (e.g. KIP) beep only when "sound" is present.
METHOD_BY_STATE = {
    "alarm": ["visual", "sound"],
    "alert": ["visual"],
    "warn": ["visual"],
    "normal": [],
}

# Guardian Cause (item 87) enum values that warrant an audible alarm: the
# overheat and oil-pressure engine-protection set.
CRITICAL_GUARDIAN_CAUSES = {
    "GC_CHI",
    "GC_TEMPERATURE_HIGH",
    "GC_BLK_PRESS_LOW",
    "GC_LOW_OIL",
    "GC_CRITICAL_OIL",
    "GC_OIL_PRESSURE",
}

# Seven-Function Gauge (item 97) bit flags that warrant an audible alarm.
CRITICAL_BITFIELD_FLAGS = {
    "Oil Fault",
    "Water Pressure Fault",
    "Coolant Temperature Fault",
}

# Universal fault codes (fault_key) recorded as critical in the native app.
CRITICAL_FAULT_KEYS: set = {"1104-21", "1109-23", "3061-16", "4602-23"}

_ALLOWLISTS = {
    "guardian": CRITICAL_GUARDIAN_CAUSES,
    "bitfield": CRITICAL_BITFIELD_FLAGS,
    "fault": CRITICAL_FAULT_KEYS,
}


def is_critical(kind: str, key: str) -> bool:
    """True if this condition should raise an audible alarm. Unknown kinds
    (e.g. "mil") match nothing and are therefore never critical."""
    return key in _ALLOWLISTS.get(kind, ())


def state_for(kind: str, key: str, is_active: bool) -> str:
    """Return the SignalK notification state for a condition.

    inactive -> "normal"; active + critical -> "alarm"; active otherwise ->
    "alert" (fail-quiet: anything we do not recognize stays silent)."""
    if not is_active:
        return "normal"
    return "alarm" if is_critical(kind, key) else "alert"


def method_for(state: str) -> list:
    """Return a fresh method list for a state; unknown state -> []."""
    return list(METHOD_BY_STATE.get(state, []))
