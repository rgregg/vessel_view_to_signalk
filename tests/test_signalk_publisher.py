"""Tests for the SignalK Publisher"""

import asyncio
import json
import unittest
from unittest.mock import AsyncMock
from vvm_to_signalk.signalk_publisher import SignalKPublisher, SignalKConfig
from vvm_to_signalk.fault_decoder import Fault


class FakeWS:
    def __init__(self): self.sent = []
    async def send(self, msg): self.sent.append(json.loads(msg))


def test_accept_fault_emits_notification():
    pub = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    ws = FakeWS()
    pub._SignalKPublisher__websocket = ws
    pub.socket_connected = True
    fault = Fault("Legacy", 1, True, 1111)
    asyncio.run(pub.accept_fault(fault))
    delta = ws.sent[0]["updates"][0]["values"][0]
    assert delta["path"] == "notifications.propulsion.starboard.vvmFault.1111-Legacy"
    assert delta["value"]["state"] == "alarm"
    assert delta["value"]["method"] == ["visual", "sound"]
    assert delta["value"]["vvm"]["faultId"] == 1111


def test_accept_fault_cleared_is_normal():
    pub = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    ws = FakeWS(); pub._SignalKPublisher__websocket = ws; pub.socket_connected = True
    asyncio.run(pub.accept_fault(Fault("Legacy", 1, False, 1111)))
    delta = ws.sent[0]["updates"][0]["values"][0]
    assert delta["value"]["state"] == "normal"
    assert delta["value"]["method"] == []


def test_accept_fault_message_includes_known_description():
    pub = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    ws = FakeWS(); pub._SignalKPublisher__websocket = ws; pub.socket_connected = True
    asyncio.run(pub.accept_fault(Fault("Universal", 1, True, 946, failure_type_id=6)))
    delta = ws.sent[0]["updates"][0]["values"][0]
    assert "Emissions Control Fault" in delta["value"]["message"]
    assert "946-6" in delta["value"]["message"]
    assert delta["value"]["vvm"]["description"] == "Emissions Control Fault"


def test_accept_fault_message_bare_code_when_unknown():
    pub = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    ws = FakeWS(); pub._SignalKPublisher__websocket = ws; pub.socket_connected = True
    asyncio.run(pub.accept_fault(Fault("Legacy", 1, True, 1111)))
    delta = ws.sent[0]["updates"][0]["values"][0]
    assert "1111-Legacy" in delta["value"]["message"]
    assert delta["value"]["vvm"]["description"] is None


class FakeItem:
    """Minimal stand-in for DataItem used in publisher tests."""
    def __init__(self, item_id=1, name="RPM", units="revs/minute", is_vessel=False):
        self.id = item_id
        self.name = name
        self.units = units
        self.is_vessel = is_vessel


class TestSignalKPublisher(unittest.IsolatedAsyncioTestCase):
    """Test the SignalK Publisher"""

    def setUp(self):
        """Set up the test"""
        self.config = SignalKConfig()
        self.config.websocket_url = "ws://localhost:3000/signalk/v1/stream"
        self.health_status = {}
        self.publisher = SignalKPublisher(self.config, self.health_status)

    async def test_generate_delta(self):
        """Test that the delta message is generated correctly"""
        path = "propulsion.port.revolutions"
        value = 1000
        delta = self.publisher.generate_delta(path, value)
        self.assertEqual(delta["context"], "vessels.self")
        self.assertEqual(len(delta["updates"]), 1)
        self.assertEqual(delta["updates"][0]["values"][0]["path"], path)
        self.assertEqual(delta["updates"][0]["values"][0]["value"], value)

    async def test_accept_engine_data_known_path(self):
        """Engine data for a known item is sent with SI-converted value."""
        mock_websocket = AsyncMock()
        self.publisher.socket_connected = True
        self.publisher._SignalKPublisher__websocket = mock_websocket

        item = FakeItem(item_id=1, name="RPM", units="revs/minute")
        await self.publisher.accept_engine_data(item, 1, 600.0)

        mock_websocket.send.assert_called_once()
        import json
        sent = json.loads(mock_websocket.send.call_args[0][0])
        values = sent["updates"][0]["values"]
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0]["path"], "propulsion.starboard.revolutions")
        self.assertAlmostEqual(values[0]["value"], 600.0 / 60.0)  # Hz

    async def test_accept_engine_data_unknown_skipped(self):
        """Engine data for an unmapped item is skipped by default."""
        mock_websocket = AsyncMock()
        self.publisher.socket_connected = True
        self.publisher._SignalKPublisher__websocket = mock_websocket

        item = FakeItem(item_id=9999, name="UnknownValue", units="")
        await self.publisher.accept_engine_data(item, 1, 42.0)
        mock_websocket.send.assert_not_called()

    async def test_accept_engine_data_unknown_included_when_configured(self):
        """Engine data for an unmapped item is sent when send_unknown_parameters=True."""
        mock_websocket = AsyncMock()
        self.publisher.socket_connected = True
        self.publisher._SignalKPublisher__websocket = mock_websocket
        self.config.send_unknown_parameters = True

        item = FakeItem(item_id=9999, name="UnknownValue", units="")
        await self.publisher.accept_engine_data(item, 1, 42.0)
        mock_websocket.send.assert_called_once()

    def test_update_active_items_is_noop(self):
        """update_active_items should not raise."""
        self.publisher.update_active_items([1, 2, 3])


def test_engine_labels_parsed_from_config():
    cfg = SignalKConfig({"websocket-url": "ws://x",
                         "engine-labels": {1: "port", 2: "starboard"}})
    assert cfg.engine_labels == {1: "port", 2: "starboard"}


def test_engine_labels_default_none():
    assert SignalKConfig({"websocket-url": "ws://x"}).engine_labels is None


def test_guardian_cause_active_emits_alarm():
    p = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    from vvm_to_signalk.data_dictionary import DataDictionary
    D = DataDictionary.load()

    class WS:
        def __init__(self): self.sent = []
        async def send(self, m): self.sent.append(json.loads(m))

    ws = WS()
    p._SignalKPublisher__websocket = ws
    p.socket_connected = True
    asyncio.run(p.accept_engine_data(D.by_id(87), 1, 4))  # GC_LOW_OIL
    v = ws.sent[0]["updates"][0]["values"][0]
    assert v["path"] == "notifications.propulsion.starboard.guardianCause"
    assert v["value"]["state"] == "alarm"
    assert v["value"]["message"].endswith("GC_LOW_OIL")


def test_guardian_cause_none_is_normal():
    p = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    from vvm_to_signalk.data_dictionary import DataDictionary
    D = DataDictionary.load()

    class WS:
        def __init__(self): self.sent = []
        async def send(self, m): self.sent.append(json.loads(m))

    ws = WS()
    p._SignalKPublisher__websocket = ws
    p.socket_connected = True
    asyncio.run(p.accept_engine_data(D.by_id(87), 1, 0))  # GC_NONE
    assert ws.sent[0]["updates"][0]["values"][0]["value"]["state"] == "normal"


def test_seven_function_gauge_emits_per_flag():
    p = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    from vvm_to_signalk.data_dictionary import DataDictionary
    D = DataDictionary.load()

    class WS:
        def __init__(self): self.sent = []
        async def send(self, m): self.sent.append(json.loads(m))

    ws = WS()
    p._SignalKPublisher__websocket = ws
    p.socket_connected = True
    asyncio.run(p.accept_engine_data(D.by_id(97), 1, 0b00100))
    paths = {u["updates"][0]["values"][0]["path"]: u["updates"][0]["values"][0]["value"]
             for u in ws.sent}
    assert "notifications.propulsion.starboard.guardianCheckEngine" in paths
    assert paths["notifications.propulsion.starboard.guardianCheckEngine"]["state"] == "alarm"
    assert paths["notifications.propulsion.starboard.oilFault"]["state"] == "normal"


def test_mil_on_emits_alarm():
    p = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    from vvm_to_signalk.data_dictionary import DataDictionary
    D = DataDictionary.load()

    class WS:
        def __init__(self): self.sent = []
        async def send(self, m): self.sent.append(json.loads(m))

    ws = WS()
    p._SignalKPublisher__websocket = ws
    p.socket_connected = True
    asyncio.run(p.accept_engine_data(D.by_id(106), 1, 1))  # MIL Constant On
    v = ws.sent[0]["updates"][0]["values"][0]
    assert v["path"] == "notifications.propulsion.starboard.malfunctionIndicatorLightMilData"
    assert v["value"]["state"] == "alarm"
    assert v["value"]["message"].endswith("MIL Constant On")


def test_notification_deduped_until_state_changes():
    p = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    from vvm_to_signalk.data_dictionary import DataDictionary
    D = DataDictionary.load()

    class WS:
        def __init__(self): self.sent = []
        async def send(self, m): self.sent.append(json.loads(m))

    ws = WS()
    p._SignalKPublisher__websocket = ws
    p.socket_connected = True
    item = D.by_id(87)
    asyncio.run(p.accept_engine_data(item, 1, 4))  # alarm -> sent
    asyncio.run(p.accept_engine_data(item, 1, 4))  # same state -> deduped
    assert len(ws.sent) == 1
    asyncio.run(p.accept_engine_data(item, 1, 0))  # state change -> sent
    assert len(ws.sent) == 2


if __name__ == '__main__':
    unittest.main()
