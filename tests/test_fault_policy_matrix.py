"""Dictionary-driven synthetic proof of the notification policy: which VVM
conditions are audible (alarm+sound) vs silent (alert) vs cleared (normal).
Faults are synthetic — the real captures contain none."""

import asyncio
import json

from vvm_to_signalk.data_dictionary import DataDictionary
from vvm_to_signalk.fault_decoder import parse_fault, Fault
from vvm_to_signalk.signalk_publisher import SignalKPublisher, SignalKConfig
from vvm_to_signalk.notification_policy import (
    CRITICAL_GUARDIAN_CAUSES,
    CRITICAL_BITFIELD_FLAGS,
)

METHOD = {"alarm": ["visual", "sound"], "alert": ["visual"], "normal": []}


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, m):
        self.sent.append(json.loads(m))


def _fresh_pub():
    pub = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    ws = FakeWS()
    pub._SignalKPublisher__websocket = ws
    pub.socket_connected = True
    return pub, ws


def _deltas(ws):
    return [v for d in ws.sent for u in d["updates"] for v in u["values"]]


def _delta_ending(ws, suffix):
    """Return the value dict of the single delta whose path ends with suffix."""
    matches = [v["value"] for v in _deltas(ws) if v["path"].endswith(suffix)]
    assert len(matches) == 1, f"expected exactly one delta ending {suffix}, got {len(matches)}"
    return matches[0]


D = DataDictionary.load()


def test_guardian_cause_matrix():
    item = D.by_id(87)
    for raw_str, label in item.enum.items():
        value = int(raw_str)
        pub, ws = _fresh_pub()
        asyncio.run(pub.accept_engine_data(item, 1, value))
        v = _delta_ending(ws, "guardianCause")
        if value == 0:
            expected = "normal"
        elif label in CRITICAL_GUARDIAN_CAUSES:
            expected = "alarm"
        else:
            expected = "alert"
        assert v["state"] == expected, f"{label} ({value}) -> {v['state']}, want {expected}"
        assert v["method"] == METHOD[expected]


def test_mil_matrix():
    item = D.by_id(106)
    for value, expected in ((0, "normal"), (1, "alert")):
        pub, ws = _fresh_pub()
        asyncio.run(pub.accept_engine_data(item, 1, value))
        v = _delta_ending(ws, "malfunctionIndicatorLightMilData")
        assert v["state"] == expected
        assert v["method"] == METHOD[expected]


def test_bitfield_matrix_each_bit_alone():
    item = D.by_id(97)
    for pos in range(8):
        rendered = item.render_bits(1 << pos)
        active = [name for name, bit in rendered.items() if bit]
        if not active:
            continue  # reserved bit
        name = active[0]
        pub, ws = _fresh_pub()
        asyncio.run(pub.accept_engine_data(item, 1, 1 << pos))
        expected = "alarm" if name in CRITICAL_BITFIELD_FLAGS else "alert"
        # The set bit's own notification:
        matches = [v["value"] for v in _deltas(ws)
                   if v["value"]["message"].endswith(f"{name}: active")]
        assert len(matches) == 1, f"{name}: expected one active delta"
        assert matches[0]["state"] == expected, f"{name} -> {matches[0]['state']}, want {expected}"
        assert matches[0]["method"] == METHOD[expected]


def test_bitfield_matrix_multibit_combo_independent():
    """A value with two bits set classifies each flag independently in one emission."""
    item = D.by_id(97)
    # Discover one critical bit and one non-critical bit from the live dictionary.
    all_flags = item.render_bits(0xFF)  # {name: 1} for every non-reserved bit
    positions = {}
    for pos in range(8):
        active = [n for n, b in item.render_bits(1 << pos).items() if b]
        if active:
            positions[active[0]] = pos
    critical = next(n for n in positions if n in CRITICAL_BITFIELD_FLAGS)
    noncritical = next(n for n in positions if n not in CRITICAL_BITFIELD_FLAGS)
    value = (1 << positions[critical]) | (1 << positions[noncritical])

    pub, ws = _fresh_pub()
    asyncio.run(pub.accept_engine_data(item, 1, value))

    def state_method(name):
        m = [v["value"] for v in _deltas(ws)
             if v["value"]["message"].endswith(f"{name}: active")]
        assert len(m) == 1, f"expected one active delta for {name}"
        return m[0]["state"], m[0]["method"]

    assert state_method(critical) == ("alarm", METHOD["alarm"])
    assert state_method(noncritical) == ("alert", METHOD["alert"])


def test_legacy_fault_is_alert_when_active_normal_when_cleared():
    pub, ws = _fresh_pub()
    asyncio.run(pub.accept_fault(Fault("Legacy", 1, True, 1111)))
    v = _delta_ending(ws, "vvmFault.1111-Legacy")
    assert v["state"] == "alert"
    assert v["method"] == ["visual"]

    pub, ws = _fresh_pub()
    asyncio.run(pub.accept_fault(Fault("Legacy", 1, False, 1111)))
    v = _delta_ending(ws, "vvmFault.1111-Legacy")
    assert v["state"] == "normal"
    assert v["method"] == []


def test_universal_fault_severity_never_changes_state():
    for severity in range(8):
        action, failure, fault_id = 300, 12, 2222
        # Bit layout mirrors fault_decoder.parse_fault (severity<<0, action<<3, failure<<35, fault_id<<42).
        packed = (severity & 0x7) | ((action & 0x1FF) << 3) | ((failure & 0x7F) << 35) \
            | ((fault_id & 0xFFFF) << 42)
        body = packed.to_bytes(8, "little")[:7]
        fault = parse_fault(bytes([0x21, 0x01]) + body)  # type 1 Universal, engine 2, active
        assert fault.severity == severity
        pub, ws = _fresh_pub()
        asyncio.run(pub.accept_fault(fault))
        v = _delta_ending(ws, "vvmFault.2222-12")
        assert v["state"] == "alert", f"severity {severity} changed state to {v['state']}"
        assert v["method"] == ["visual"]
        assert v["vvm"]["severity"] == severity


def test_allowlist_labels_exist_in_dictionary():
    # Direction: allowlist ⊆ dictionary — catches a renamed allowlist label. (A newly
    # added critical enum left unclassified would stay silent by design, not caught here.)
    guardian_labels = set(D.by_id(87).enum.values())
    assert CRITICAL_GUARDIAN_CAUSES <= guardian_labels, \
        f"stale Guardian labels: {CRITICAL_GUARDIAN_CAUSES - guardian_labels}"
    bit_names = set(D.by_id(97).render_bits(0xFF).keys())
    assert CRITICAL_BITFIELD_FLAGS <= bit_names, \
        f"stale bitfield labels: {CRITICAL_BITFIELD_FLAGS - bit_names}"
