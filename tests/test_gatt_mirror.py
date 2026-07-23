from bless import GATTCharacteristicProperties as P, GATTAttributePermissions as Perm
from vvm_to_signalk.gatt_mirror import mirror_profile


class _FakeChar:
    def __init__(self, uuid, properties):
        self.uuid = uuid
        self.properties = properties


class _FakeService:
    def __init__(self, uuid, chars):
        self.uuid = uuid
        self.characteristics = chars


def test_mirror_maps_props_and_permissions():
    services = [_FakeService("svc-1", [
        _FakeChar("char-notify", ["notify"]),
        _FakeChar("char-rw", ["read", "write"]),
        _FakeChar("char-indicate", ["indicate"]),
    ])]
    mirrored = mirror_profile(services)
    assert len(mirrored) == 1
    svc = mirrored[0]
    assert svc.uuid == "svc-1"
    by_uuid = {c.uuid: c for c in svc.characteristics}

    assert by_uuid["char-notify"].properties & P.notify
    assert by_uuid["char-indicate"].properties & P.indicate
    rw = by_uuid["char-rw"]
    assert rw.properties & P.read
    assert rw.properties & P.write
    assert rw.permissions & Perm.readable
    assert rw.permissions & Perm.writeable
    # notify-only char is not writeable
    assert not (by_uuid["char-notify"].permissions & Perm.writeable)
