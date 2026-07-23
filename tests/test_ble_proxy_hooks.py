import asyncio

import pytest
from unittest.mock import AsyncMock

from vvm_to_signalk.ble_connection import BleDeviceConnection, BleConnectionConfig


@pytest.fixture(autouse=True)
def _restore_event_loop():
    """asyncio.run() (used below) closes its loop and clears the thread's
    current event loop; BleDeviceConnection.__init__ creates an
    asyncio.Future() and needs one to exist for later tests in this file
    or in other modules (see tests/test_blelogic.py for the same pattern)."""
    yield
    asyncio.set_event_loop(asyncio.new_event_loop())


class _FakeChar:
    def __init__(self, uuid):
        self.uuid = uuid


def _make_conn():
    cfg = BleConnectionConfig({"address": "AA:BB:CC:DD:EE:FF"})
    return BleDeviceConnection(cfg, {})


def test_observer_sees_every_notification():
    conn = _make_conn()
    seen = []
    conn.set_notification_observer(lambda uuid, data: seen.append((uuid, bytes(data))))
    # A channel notification (unknown item -> decode path) still reaches the observer.
    conn.notification_handler(_FakeChar("00000201-0000-1000-8000-ec55f9f5b963"),
                              bytearray(b"\x01\x02\x03"))
    assert seen == [("00000201-0000-1000-8000-ec55f9f5b963", b"\x01\x02\x03")]


def test_observer_cleared():
    conn = _make_conn()
    seen = []
    conn.set_notification_observer(lambda uuid, data: seen.append(uuid))
    conn.set_notification_observer(None)
    conn.notification_handler(_FakeChar("uuid"), bytearray(b"\x00"))
    assert seen == []


def test_proxy_write_uses_active_client():
    conn = _make_conn()
    client = AsyncMock()
    conn._active_client = client
    asyncio.run(conn.proxy_write("uuid-x", b"\xaa", response=True))
    client.write_gatt_char.assert_awaited_once_with("uuid-x", b"\xaa", response=True)


def test_proxy_read_without_client_raises():
    conn = _make_conn()
    conn._active_client = None
    try:
        asyncio.run(conn.proxy_read("uuid-x"))
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass


def test_set_proxy_relay_ready_and_lost_called():
    import asyncio
    conn = _make_conn()

    class _Relay:
        def __init__(self):
            self.ready = None
            self.lost = False
        async def on_upstream_ready(self, services):
            self.ready = services
        async def on_upstream_lost(self):
            self.lost = True

    relay = _Relay()
    conn.set_proxy_relay(relay)
    # the connection exposes helpers the loop calls; test them directly
    asyncio.run(conn._proxy_notify_ready(["svc"]))
    assert relay.ready == ["svc"]
    asyncio.run(conn._proxy_notify_lost())
    assert relay.lost is True
