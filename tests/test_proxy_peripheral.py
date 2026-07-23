import asyncio

from vvm_to_signalk.gatt_mirror import MirroredService, MirroredChar
from vvm_to_signalk.proxy_peripheral import VvmProxyPeripheral


class _FakeServer:
    def __init__(self, name, **kw):
        self.name = name
        self.services_added = []
        self.chars_added = []
        self.started = False
        self.stopped = False
        self.updated = []
        self.read_request_func = None
        self.write_request_func = None
        self._values = {}

    async def add_new_service(self, uuid):
        self.services_added.append(uuid)

    async def add_new_characteristic(self, svc, uuid, props, value, perms):
        self.chars_added.append((svc, uuid))
        self._values[uuid] = bytearray(value or b"")

    def get_characteristic(self, uuid):
        class _C:
            pass
        c = _C()
        c.value = self._values.get(uuid, bytearray())
        c.uuid = uuid
        self._values[uuid] = c.value
        return c

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    def update_value(self, svc, uuid):
        self.updated.append((svc, uuid))
        return True


def _peripheral(writes, reads):
    mirrored = [MirroredService("svc-1", [
        MirroredChar("char-a", 0x10, 0x01),
        MirroredChar("char-b", 0x08, 0x02),
    ])]
    servers = {}

    def factory(name, **kw):
        s = _FakeServer(name, **kw)
        servers["s"] = s
        return s

    p = VvmProxyPeripheral(
        "VVM_TEST", mirrored,
        on_write=lambda uuid, data: writes.append((uuid, bytes(data))),
        on_read=lambda uuid: reads.get(uuid, b""),
        server_factory=factory,
    )
    return p, servers


def test_start_builds_profile_and_advertises():
    p, servers = _peripheral([], {})
    asyncio.run(p.start())
    s = servers["s"]
    assert s.services_added == ["svc-1"]
    assert set(u for _, u in s.chars_added) == {"char-a", "char-b"}
    assert s.started is True


def test_push_notification_updates_value():
    p, servers = _peripheral([], {})
    asyncio.run(p.start())
    asyncio.run(p.push_notification("char-a", b"\x99"))
    s = servers["s"]
    assert ("svc-1", "char-a") in s.updated


def test_push_unknown_uuid_is_ignored():
    p, servers = _peripheral([], {})
    asyncio.run(p.start())
    asyncio.run(p.push_notification("nope", b"\x01"))  # must not raise
    assert ("svc-1", "nope") not in servers["s"].updated


def test_write_callback_invoked():
    writes = []
    p, servers = _peripheral(writes, {})
    asyncio.run(p.start())
    s = servers["s"]
    # simulate bless invoking the registered write handler

    class _C:
        uuid = "char-b"
    s.write_request_func(_C(), bytearray(b"\x42"))
    assert writes == [("char-b", b"\x42")]
