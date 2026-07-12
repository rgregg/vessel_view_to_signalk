"""Tests for BLE device logic"""

import logging
import unittest
import asyncio
import sys
from unittest.mock import patch
from bleak import BleakGATTCharacteristic
from bleak.exc import BleakCharacteristicNotFoundError
from vvm_to_signalk.ble_connection import BleDeviceConnection, BleConnectionConfig
from vvm_to_signalk.config_decoder import ConfigDecoder
from vvm_to_signalk.data_dictionary import DataDictionary

logger = logging.getLogger(__name__)

class FakeReceiver:
    """Fake receiver that captures decoded engine data calls."""
    def __init__(self):
        self.calls = []

    async def accept_engine_data(self, item, engine_id, value):
        """Capture a decoded engine data call."""
        self.calls.append((item.id, engine_id, value))

    def update_active_items(self, item_ids):
        """Capture active item IDs."""
        self.active = item_ids


class FakeChar:
    """Minimal stand-in for BleakGATTCharacteristic."""
    def __init__(self, uuid):
        self.uuid = uuid


def test_notification_decodes_all_engines():
    """BLE notification handler decodes multi-engine payloads via the dictionary."""
    health = {}
    conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), health)
    rx = FakeReceiver()
    conn.accept_data_receiver(rx)
    conn._dictionary = DataDictionary.load()
    conn._max_engines = 2
    # id 1 (RPM), engine1=600 (0x0258), engine2=1000 (0x03E8)
    data = bytearray.fromhex("0100" + "5802" + "e803")
    conn.notification_handler(FakeChar("00000102-0000-1000-8000-ec55f9f5b963"), data)
    # allow the scheduled publish tasks to run
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
    assert (1, 1, 600.0) in rx.calls
    assert (1, 2, 1000.0) in rx.calls


def test_update_active_engines_parses_bitfield():
    """Data-item 10000 (Active Engines) bitfield populates the active-engine set."""
    conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})
    conn._dictionary = DataDictionary.load()
    # id 10000 (0x2710 -> LE "1027"), bitfield 0x03 = engines 1 and 2 active
    conn.notification_handler(FakeChar("00000109-0000-1000-8000-ec55f9f5b963"),
                              bytearray.fromhex("1027" + "03"))
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
    assert conn._active_engine_ids == {1, 2}


def test_inactive_engine_excluded():
    """Values for engines not in the active set are not published."""
    conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})
    rx = FakeReceiver()
    conn.accept_data_receiver(rx)
    conn._dictionary = DataDictionary.load()
    conn._max_engines = 2
    conn._active_engine_ids = {1}  # only engine 1 active
    # id 1 (RPM), engine1=600 (0x0258), engine2=1000 (0x03E8)
    conn.notification_handler(FakeChar("00000102-0000-1000-8000-ec55f9f5b963"),
                              bytearray.fromhex("0100" + "5802" + "e803"))
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
    assert (1, 1, 600.0) in rx.calls
    assert all(engine_id != 2 for _id, engine_id, _value in rx.calls)


def test_failing_receiver_exception_is_logged(caplog):
    """A receiver that raises must have its exception observed and logged,
    not silently swallowed by a fire-and-forget task."""
    conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})

    class FailingReceiver:
        """Receiver that always raises when handed data"""
        async def accept_engine_data(self, item, engine_id, value):
            raise RuntimeError("boom")

        def update_active_items(self, item_ids):
            pass

    conn.accept_data_receiver(FailingReceiver())
    conn._dictionary = DataDictionary.load()
    conn._max_engines = 1

    with caplog.at_level(logging.WARNING, logger="vvm_to_signalk.ble_connection"):
        conn.notification_handler(FakeChar("00000102-0000-1000-8000-ec55f9f5b963"),
                                  bytearray.fromhex("0100" + "5802"))
        # allow the scheduled task and its done-callback to run
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.01))

    assert any("boom" in r.getMessage() for r in caplog.records)


def test_retrieve_device_info_handles_missing_characteristics():
    """A device missing standard characteristics must not crash init."""
    conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})

    class MissingCharsClient:
        """Fake client whose characteristic reads all report 'not found'"""
        is_connected = True

        async def read_gatt_char(self, uuid):
            """Every standard characteristic is absent on this device"""
            raise BleakCharacteristicNotFoundError(uuid)

    # Must not raise even though every characteristic read returns None
    asyncio.get_event_loop().run_until_complete(
        conn._retrieve_device_info(MissingCharsClient()))


def test_setup_data_notifications_skips_indicate_only():
    """Regression: the VVM drops the BLE link (ATT 0x0e) if we subscribe to its
    indicate-type control characteristics (0x301/0x302/0x401, 0x2a05). Only
    'notify' characteristics carry streaming data, so indicate-only ones must
    not be subscribed."""
    asyncio.set_event_loop(asyncio.new_event_loop())
    conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})

    class PropChar:
        """Characteristic stand-in carrying a uuid and GATT properties."""
        def __init__(self, uuid, properties):
            self.uuid = uuid
            self.properties = properties

    class FakeService:
        """Service exposing a fixed list of characteristics."""
        def __init__(self, characteristics):
            self.characteristics = characteristics

    notify_char = PropChar("00000102-0000-1000-8000-ec55f9f5b963", ["read", "notify"])
    indicate_char = PropChar("00000401-0000-1000-8000-ec55f9f5b963", ["read", "indicate"])
    service_changed = PropChar("00002a05-0000-1000-8000-00805f9b34fb", ["indicate"])

    subscribed = []

    class FakeClient:
        """Captures which characteristic UUIDs get a start_notify."""
        services = [FakeService([notify_char, indicate_char, service_changed])]

        async def start_notify(self, uuid, _handler):
            subscribed.append(uuid)

    asyncio.get_event_loop().run_until_complete(
        conn._setup_data_notifications(FakeClient()))

    assert notify_char.uuid in subscribed
    assert indicate_char.uuid not in subscribed
    assert service_changed.uuid not in subscribed


class Test_ConnectionLifecycle(unittest.IsolatedAsyncioTestCase):
    """Tests for the connect / reconnect lifecycle"""

    async def test_connection_timeout_passed_to_bleak_client(self):
        """The configured connection timeout must be handed to BleakClient."""
        config = BleConnectionConfig()
        config.device_name = "UnitTestRunner"
        config.connection_timeout = 17.0
        decoder = BleDeviceConnection(config, {})

        captured = {}

        class FakeClient:
            """Records constructor args then bails out of the context manager"""
            def __init__(self, device, disconnected_callback=None, timeout=None, **kwargs):
                captured["timeout"] = timeout

            async def __aenter__(self):
                raise RuntimeError("stop after construction")

            async def __aexit__(self, *args):
                return False

        with patch("vvm_to_signalk.ble_connection.BleakClient", FakeClient):
            await decoder._device_init_and_loop("fake-device")

        assert captured["timeout"] == 17.0

    async def test_run_backs_off_after_failed_connection(self):
        """After a failed connection cycle the loop should wait retry_interval
        before scanning again, instead of busy-looping."""
        config = BleConnectionConfig()
        config.device_name = "UnitTestRunner"
        config.retry_interval = 7
        decoder = BleDeviceConnection(config, {})

        sleeps = []

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        cycles = {"n": 0}

        async def fake_scan():
            return "fake-device"

        async def fake_init(_device):
            cycles["n"] += 1
            if cycles["n"] >= 2:
                await decoder.close()
            return False

        decoder._scan_for_device = fake_scan
        decoder._device_init_and_loop = fake_init

        with patch("vvm_to_signalk.ble_connection.asyncio.sleep", fake_sleep):
            await decoder.run(task_group=None)

        assert 7 in sleeps


class _HexCountingBytes(bytearray):
    """A bytearray that records how many times .hex() is called on it."""
    def hex(self, *args, **kwargs):
        self.hex_calls = getattr(self, "hex_calls", 0) + 1
        return bytearray.hex(self, *args, **kwargs)


def test_set_health_ok_without_message_is_not_noisy(caplog):
    """Clearing the health state with no message must not log a placeholder
    line on every healthy transition."""
    # A prior IsolatedAsyncioTestCase may have closed the loop; ensure one exists
    # because BleDeviceConnection.__init__ creates an asyncio.Future.
    asyncio.set_event_loop(asyncio.new_event_loop())
    conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})
    with caplog.at_level(logging.INFO, logger="vvm_to_signalk.ble_connection"):
        conn._set_health(True)
    assert caplog.records == []


def test_notification_handler_skips_hex_when_debug_disabled():
    """The per-notification hot path must not pay for data.hex() when
    debug logging is turned off."""
    ble_logger = logging.getLogger("vvm_to_signalk.ble_connection")
    old_level = ble_logger.level
    ble_logger.setLevel(logging.INFO)
    try:
        # Ensure a current event loop exists (a prior IsolatedAsyncioTestCase
        # may have closed it); __init__ creates an asyncio.Future.
        asyncio.set_event_loop(asyncio.new_event_loop())
        conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})
        conn._dictionary = DataDictionary.load()
        conn._max_engines = 1
        # id 1 (RPM), engine1=600 (0x0258)
        data = _HexCountingBytes(bytes.fromhex("0100" + "5802"))
        conn.notification_handler(
            FakeChar("00000102-0000-1000-8000-ec55f9f5b963"), data)
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
        assert getattr(data, "hex_calls", 0) == 0
    finally:
        ble_logger.setLevel(old_level)


def test_unparsed_channel_data_is_logged_at_warning(caplog):
    """A channel notification we can't decode (unknown data-item ID) must be
    surfaced at WARNING with the raw hex, not silently dropped — otherwise a
    new/unknown item is invisible at the deployed INFO log level."""
    conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})
    conn._dictionary = DataDictionary.load()
    conn._max_engines = 1
    # id 9999 (0x270F -> LE "0f27") is not in the data dictionary.
    with caplog.at_level(logging.WARNING, logger="vvm_to_signalk.ble_connection"):
        conn.notification_handler(FakeChar("00000102-0000-1000-8000-ec55f9f5b963"),
                                  bytearray.fromhex("0f27" + "abcd"))
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0f27abcd" in m for m in msgs), msgs


def test_unparsed_channel_data_deduped_per_connection(caplog):
    """The same unknown item must be logged only once per connection even as
    its value bytes change every notification, so a persistent unknown stream
    at ~20 Hz doesn't flood the log."""
    conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})
    conn._dictionary = DataDictionary.load()
    conn._max_engines = 1
    char = FakeChar("00000102-0000-1000-8000-ec55f9f5b963")
    with caplog.at_level(logging.WARNING, logger="vvm_to_signalk.ble_connection"):
        conn.notification_handler(char, bytearray.fromhex("0f27" + "abcd"))
        conn.notification_handler(char, bytearray.fromhex("0f27" + "1234"))
        conn.notification_handler(char, bytearray.fromhex("0f27" + "0000"))
    warnings = [r for r in caplog.records if "0f27" in r.getMessage()]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]


def test_distinct_unparsed_items_each_logged(caplog):
    """Two different unknown item IDs must each be logged once."""
    conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})
    conn._dictionary = DataDictionary.load()
    conn._max_engines = 1
    char = FakeChar("00000102-0000-1000-8000-ec55f9f5b963")
    with caplog.at_level(logging.WARNING, logger="vvm_to_signalk.ble_connection"):
        conn.notification_handler(char, bytearray.fromhex("0f27" + "abcd"))  # id 9999
        conn.notification_handler(char, bytearray.fromhex("0e27" + "abcd"))  # id 9998
    assert any("0f27" in r.getMessage() for r in caplog.records)
    assert any("0e27" in r.getMessage() for r in caplog.records)


def test_unparsed_dedup_resets_between_connections(caplog):
    """The dedup memory is per-connection: after a reconnect the same unknown
    item is logged again (a fresh connection may reveal it changed)."""
    conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})
    conn._dictionary = DataDictionary.load()
    conn._max_engines = 1
    char = FakeChar("00000102-0000-1000-8000-ec55f9f5b963")
    with caplog.at_level(logging.WARNING, logger="vvm_to_signalk.ble_connection"):
        conn.notification_handler(char, bytearray.fromhex("0f27" + "abcd"))
        conn._reset_unparsed_tracking()  # what a new connection does
        conn.notification_handler(char, bytearray.fromhex("0f27" + "abcd"))
    warnings = [r for r in caplog.records if "0f27" in r.getMessage()]
    assert len(warnings) == 2, [r.getMessage() for r in warnings]


def test_known_item_not_warned(caplog):
    """A normally-decodable notification must not produce an unparsed warning."""
    conn = BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})
    conn._dictionary = DataDictionary.load()
    conn._max_engines = 1
    with caplog.at_level(logging.WARNING, logger="vvm_to_signalk.ble_connection"):
        conn.notification_handler(FakeChar("00000102-0000-1000-8000-ec55f9f5b963"),
                                  bytearray.fromhex("0100" + "5802"))  # id 1 RPM
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0))
    assert not any("Unparsed" in r.getMessage() for r in caplog.records)


FAULT_UUID = "00000201-0000-1000-8000-ec55f9f5b963"


def _fresh_conn():
    """A connection on a fresh event loop (prior IsolatedAsyncioTestCase may
    have closed the loop; __init__ creates an asyncio.Future)."""
    asyncio.set_event_loop(asyncio.new_event_loop())
    return BleDeviceConnection(BleConnectionConfig({"name": "x"}), {})


def test_fault_alert_subscribes_when_enabled():
    """When not disabled, the helper subscribes to 0x201 and leaves clean state."""
    conn = _fresh_conn()
    subscribed = []

    class FakeClient:
        async def start_notify(self, uuid, _handler):
            subscribed.append(uuid)

    asyncio.get_event_loop().run_until_complete(conn._subscribe_fault_alert(FakeClient()))
    assert FAULT_UUID in subscribed
    assert conn._fault_subscribe_disabled is False
    assert conn._fault_subscribe_pending is False


def test_fault_alert_subscribe_failure_disables_and_skips_next():
    """A rejected CCCD write (the #37 ATT 0x0e) must be swallowed, disable the
    subscription, and cause the next attempt to skip start_notify entirely."""
    conn = _fresh_conn()
    calls = []

    class FailingClient:
        async def start_notify(self, uuid, _handler):
            calls.append(uuid)
            raise Exception("ATT error 0x0e (Unlikely Error)")

    loop = asyncio.get_event_loop()
    loop.run_until_complete(conn._subscribe_fault_alert(FailingClient()))  # must not raise
    assert conn._fault_subscribe_disabled is True
    assert conn._fault_subscribe_pending is False
    # Second attempt: disabled -> start_notify not called again
    loop.run_until_complete(conn._subscribe_fault_alert(FailingClient()))
    assert calls == [FAULT_UUID]


def test_fault_alert_skipped_when_disabled():
    """A pre-disabled connection never touches 0x201."""
    conn = _fresh_conn()
    conn._fault_subscribe_disabled = True
    called = []

    class FakeClient:
        async def start_notify(self, uuid, _handler):
            called.append(uuid)

    asyncio.get_event_loop().run_until_complete(conn._subscribe_fault_alert(FakeClient()))
    assert called == []


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr)
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()
