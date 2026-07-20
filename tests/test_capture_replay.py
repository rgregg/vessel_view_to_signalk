"""Replay real captured healthy telemetry through the decode+publish pipeline
and assert it never raises a notification/audible alarm, never hits an unparsed
channel, and decodes known golden values."""

import asyncio
import json
import os

from vvm_to_signalk.data_dictionary import DataDictionary, decode_notification
from vvm_to_signalk.signalk_publisher import SignalKPublisher, SignalKConfig

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "capture_healthy.jsonl")
EXPECTED_IDS = {1, 10, 150, 181, 182, 210, 212, 232, 251, 6000, 8000, 10000}


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, m):
        self.sent.append(json.loads(m))


def _load_rows():
    with open(FIXTURE) as f:
        return [json.loads(line) for line in f if line.strip()]


def _replay():
    """Replay every fixture frame; return (publisher_ws_deltas, decoded_id_set)."""
    d = DataDictionary.load()
    pub = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    ws = FakeWS()
    pub._SignalKPublisher__websocket = ws
    pub.socket_connected = True
    ids = set()

    async def run():
        for row in _load_rows():
            item, values = decode_notification(bytes.fromhex(row["hex"]), d)
            assert item is not None, f"unparsed frame {row['hex']}"
            ids.add(item.id)
            for engine_id, value in enumerate(values, start=1):
                await pub.accept_engine_data(item, engine_id, value)

    asyncio.run(run())
    return ws.sent, ids


def _values(deltas):
    out = []
    for d in deltas:
        for u in d["updates"]:
            for v in u["values"]:
                out.append(v)
    return out


def test_healthy_replay_emits_no_notifications_or_sound():
    deltas, _ = _replay()
    for v in _values(deltas):
        assert not v["path"].startswith("notifications."), f"unexpected notification: {v}"
        val = v["value"]
        if isinstance(val, dict) and "method" in val:
            assert "sound" not in val["method"], f"unexpected audible alarm: {v}"


def test_healthy_replay_all_channels_known():
    _, ids = _replay()
    assert ids == EXPECTED_IDS


def test_healthy_replay_golden_voltage():
    deltas, _ = _replay()
    numeric = [v["value"] for v in _values(deltas) if isinstance(v["value"], (int, float))]
    # Voltage item 232 is a constant 0x38bb * 0.001 = 14.523 V in capture 1.
    assert any(abs(n - 14.523) < 0.01 for n in numeric), "golden voltage 14.523 V not found"
    assert numeric, "replay produced no numeric telemetry deltas"
