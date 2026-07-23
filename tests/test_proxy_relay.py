import asyncio

from vvm_to_signalk.proxy_config import ProxyConfig
from vvm_to_signalk.proxy_relay import ProxyRelay


class _FakeConn:
    def __init__(self, read_values=None, write_error=None):
        self.observer = None
        self.writes = []
        self.reads = []
        self._read_values = read_values or {}
        self._write_error = write_error
    def set_notification_observer(self, cb):
        self.observer = cb
    async def proxy_write(self, uuid, data, response=True):
        if self._write_error is not None:
            raise self._write_error
        self.writes.append((uuid, bytes(data)))
    async def proxy_read(self, uuid):
        self.reads.append(uuid)
        return self._read_values.get(uuid, b"")


class _FakePeripheral:
    def __init__(self, name, mirrored, on_write, on_read, **kw):
        self.name = name
        self.on_write = on_write
        self.on_read = on_read
        self.started = False
        self.stopped = False
        self.pushed = []
    async def start(self):
        self.started = True
    async def stop(self):
        self.stopped = True
    async def push_notification(self, uuid, data):
        self.pushed.append((uuid, bytes(data)))


class _FakeChar:
    def __init__(self, uuid, props):
        self.uuid = uuid
        self.properties = props


class _FakeService:
    def __init__(self, uuid, chars):
        self.uuid = uuid
        self.characteristics = chars


def _relay(conn=None):
    conn = conn if conn is not None else _FakeConn()
    made = {}
    def pf(name, mirrored, on_write, on_read, **kw):
        p = _FakePeripheral(name, mirrored, on_write, on_read, **kw)
        made["p"] = p
        return p
    relay = ProxyRelay(conn, ProxyConfig({"enabled": True}), "VVM_TEST",
                       asyncio.get_event_loop(), peripheral_factory=pf)
    return relay, conn, made


def test_ready_starts_peripheral_and_registers_observer():
    async def run():
        relay, conn, made = _relay()
        services = [_FakeService("svc", [_FakeChar("c1", ["notify"])])]
        await relay.on_upstream_ready(services)
        assert made["p"].started is True
        assert conn.observer is not None
    asyncio.run(run())


def test_notification_is_cached_and_forwarded():
    async def run():
        relay, conn, made = _relay()
        services = [_FakeService("svc", [_FakeChar("c1", ["notify"])])]
        await relay.on_upstream_ready(services)
        conn.observer("c1", b"\x07")           # simulate a VVM notification
        await asyncio.sleep(0)                  # let scheduled task run
        assert ("c1", b"\x07") in made["p"].pushed
        assert relay._serve_read("c1") == b"\x07"   # cached for reads
    asyncio.run(run())


def test_app_write_forwarded_to_vvm():
    async def run():
        relay, conn, made = _relay()
        services = [_FakeService("svc", [_FakeChar("c1", ["write"])])]
        await relay.on_upstream_ready(services)
        made["p"].on_write("c1", b"\x42")       # simulate app write
        await asyncio.sleep(0)
        assert ("c1", b"\x42") in conn.writes
    asyncio.run(run())


def test_lost_stops_peripheral_and_clears_observer():
    async def run():
        relay, conn, made = _relay()
        services = [_FakeService("svc", [_FakeChar("c1", ["notify"])])]
        await relay.on_upstream_ready(services)
        await relay.on_upstream_lost()
        assert made["p"].stopped is True
        assert conn.observer is None
    asyncio.run(run())


def test_readable_chars_are_prefetched_into_read_cache():
    async def run():
        conn = _FakeConn(read_values={"c1": b"MODEL-X"})
        relay, conn, made = _relay(conn)
        services = [_FakeService("svc", [
            _FakeChar("c1", ["read"]),
            _FakeChar("c2", ["notify"]),
        ])]
        await relay.on_upstream_ready(services)
        assert relay._serve_read("c1") == b"MODEL-X"
        assert "c1" in conn.reads
        assert "c2" not in conn.reads
    asyncio.run(run())


def test_forward_write_failure_is_logged_not_raised(caplog):
    async def run():
        conn = _FakeConn(write_error=RuntimeError("boom"))
        relay, conn, made = _relay(conn)
        services = [_FakeService("svc", [_FakeChar("c1", ["write"])])]
        await relay.on_upstream_ready(services)
        with caplog.at_level("WARNING"):
            made["p"].on_write("c1", b"\x42")   # should not raise
            for _ in range(5):
                await asyncio.sleep(0)
        assert "proxy scheduled op failed" in caplog.text
    asyncio.run(run())
