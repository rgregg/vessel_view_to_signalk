"""Mirror a discovered VVM GATT profile into bless service/characteristic specs."""
from dataclasses import dataclass

from bless import GATTCharacteristicProperties as P, GATTAttributePermissions as Perm

_PROP_MAP = {
    "read": P.read,
    "write": P.write,
    "write-without-response": P.write_without_response,
    "notify": P.notify,
    "indicate": P.indicate,
}


@dataclass
class MirroredChar:
    uuid: str
    properties: int
    permissions: int


@dataclass
class MirroredService:
    uuid: str
    characteristics: list


def mirror_profile(services) -> list:
    """Convert bleak-discovered services into a list of MirroredService."""
    result = []
    for service in services:
        chars = []
        for characteristic in service.characteristics:
            props = P(0)      # enum.Flag empty; NOT int 0 (int | Flag raises TypeError)
            perms = Perm(0)
            for name in characteristic.properties:
                flag = _PROP_MAP.get(name)
                if flag is not None:
                    props |= flag
                if name == "read":
                    perms |= Perm.readable
                if name in ("write", "write-without-response"):
                    perms |= Perm.writeable
            chars.append(MirroredChar(characteristic.uuid, props, perms))
        result.append(MirroredService(service.uuid, chars))
    return result
