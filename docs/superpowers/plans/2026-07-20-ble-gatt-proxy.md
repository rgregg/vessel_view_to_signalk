# BLE GATT Proxy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the native SmartCraft app and the connector both use the VVM over its single BLE connection slot, by making the connector a transparent BLE GATT proxy (peripheral to the app, central to the VVM) that also captures all relayed traffic.

**Architecture:** One process, two BLE roles on `hci0`. The existing `bleak` central (`BleDeviceConnection`) holds the VVM link and keeps feeding SignalK. A new `bless` peripheral (`VvmProxyPeripheral`) clones the VVM's GATT profile and lets the app connect. A `ProxyRelay` forwards notifications VVM→app and writes/subscribes/reads app→VVM, and a `TrafficCapture` logs every relayed op. Everything is behind an opt-in `proxy` config flag (default off) — off means today's behavior, unchanged.

**Tech Stack:** Python 3.11+ asyncio, `bleak==3.0.2` (central, existing), `bless` (peripheral, new), `PyYAML`, pytest.

## Global Constraints

- **Opt-in, default off.** With `proxy.enabled` false/absent, the connector's runtime behavior is byte-for-byte unchanged. No proxy object is constructed.
- **Single radio (`hci0`).** Concurrent central+peripheral. Dual-adapter is a documented fallback only; do not build it.
- **No pairing/bonding/encryption.** The VVM link is open GATT; do not add security handshakes.
- **App selects by name**, advertising `VVM_84FD27D92CBE` (from `ble-device.name`), cloned service UUIDs, our own MAC. No MAC-cloning.
- **Advertise only while the upstream VVM link is up and streaming.** When upstream drops, stop advertising and drop the app.
- **SignalK is independent of the app.** The central does its normal bootstrap init so data flows with no app connected.
- **Custom service base:** `0000XXXX-0000-1000-8000-ec55f9f5b963`. Fault char `0x0201` and control chars `0x0301/0x0302/0x0401/0x2a05` are indicate-type.
- **Follow existing test style:** pytest, fakes patching `vvm_to_signalk.<module>.<Symbol>` (see `tests/test_blelogic.py`). No network/BLE in unit tests.
- Spec: `docs/superpowers/specs/2026-07-20-ble-gatt-proxy-design.md`.

## File Structure

- Create `vvm_to_signalk/traffic_capture.py` — `TrafficCapture`: append-only timestamped hex log of relayed ops. No BLE deps.
- Create `vvm_to_signalk/proxy_config.py` — `ProxyConfig`: parses the `proxy` config section; `.valid`/`.enabled`.
- Create `vvm_to_signalk/gatt_mirror.py` — `GattProfileMirror`: turns discovered bleak services into a spec of bless services/chars.
- Create `vvm_to_signalk/proxy_peripheral.py` — `VvmProxyPeripheral`: wraps a `bless` GATT server; advertising, read/write callbacks, notification push.
- Create `vvm_to_signalk/proxy_relay.py` — `ProxyRelay`: coordinator wiring central ↔ peripheral + advertising lifecycle.
- Create `tools/proxy_concurrency_spike.py` — standalone hardware go/no-go (advertise while VVM link held).
- Modify `vvm_to_signalk/ble_connection.py` — notification fan-out hook + `proxy_write`/`proxy_read` on `BleDeviceConnection`; expose discovered services.
- Modify `vvm_to_signalk/vvm_monitor.py` — `VVMConfig` reads `proxy`; `main()` constructs + runs the relay when enabled.
- Modify `requirements.txt` — add `bless`.
- Modify `vvm_monitor.example.yaml` — document the `proxy` section.
- Tests: `tests/test_traffic_capture.py`, `tests/test_proxy_config.py`, `tests/test_gatt_mirror.py`, `tests/test_ble_proxy_hooks.py`, `tests/test_proxy_relay.py`.

---

### Task 0: Add `bless` dependency + concurrency spike (HARDWARE GATE)

**Files:**
- Modify: `requirements.txt`
- Create: `tools/proxy_concurrency_spike.py`

**Interfaces:**
- Produces: nothing consumed by later tasks; this is the go/no-go that Approach A (single radio) works on the boat.

- [ ] **Step 1: Add the dependency**

Append to `requirements.txt`:
```
bless==0.3.0
```
(API verified against 0.3.0: `BlessServer(name, loop=None)`, `add_new_service(uuid)`, `add_new_characteristic(service_uuid, char_uuid, properties, value, permissions)`, `start()`/`stop()`/`update_value(service_uuid, char_uuid)` are async/bool, `read_request_func`/`write_request_func` are instance attrs. **`GATTCharacteristicProperties` and `GATTAttributePermissions` are plain `enum.Flag`, NOT `IntFlag`** — accumulate from `P(0)`/`Perm(0)`, never from int `0`.)

- [ ] **Step 2: Write the spike tool**

Create `tools/proxy_concurrency_spike.py`:
```python
"""Hardware go/no-go for the single-radio BLE proxy (Approach A).

Connects to the VVM as a central AND advertises a dummy peripheral on the same
adapter at the same time. If both hold for ~60s with no error/disconnect, the Pi
controller supports the concurrent central+peripheral roles the proxy needs.

Run ON THE BOAT PI:
    python -m tools.proxy_concurrency_spike --address 84:FD:27:D9:2C:BE
"""
import argparse
import asyncio
import logging

from bleak import BleakClient
from bless import BlessServer, GATTCharacteristicProperties, GATTAttributePermissions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("spike")

DUMMY_SERVICE = "0000fff0-0000-1000-8000-00805f9b34fb"
DUMMY_CHAR = "0000fff1-0000-1000-8000-00805f9b34fb"


async def main(address: str, name: str, hold: float):
    server = BlessServer(name=name)
    await server.add_new_service(DUMMY_SERVICE)
    await server.add_new_characteristic(
        DUMMY_SERVICE, DUMMY_CHAR,
        GATTCharacteristicProperties.read | GATTCharacteristicProperties.notify,
        bytearray(b"\x00"),
        GATTAttributePermissions.readable,
    )
    async with BleakClient(address, timeout=20.0) as client:
        log.info("CENTRAL connected to VVM %s", address)
        await server.start()
        log.info("PERIPHERAL advertising as %s -- both roles now live", name)
        log.info("Holding both for %.0fs; watch for disconnects/errors...", hold)
        await asyncio.sleep(hold)
        await server.stop()
        log.info("GO: both roles held for the full window with no error")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--address", required=True, help="VVM BLE address")
    p.add_argument("--name", default="VVM_SPIKE_TEST")
    p.add_argument("--hold", type=float, default=60.0)
    args = p.parse_args()
    asyncio.run(main(args.address, args.name, args.hold))
```

- [ ] **Step 3: Run on the boat (manual hardware gate)**

On the boat Pi (inside a container/venv per the work-in-containers rule, or ad hoc):
```bash
python -m tools.proxy_concurrency_spike --address 84:FD:27:D9:2C:BE --hold 60
```
Expected: `CENTRAL connected` → `PERIPHERAL advertising` → `GO: both roles held ...`, no disconnect. On a separate phone, confirm `VVM_SPIKE_TEST` appears in a BLE scanner while the central is connected.
**If this fails** (advertising rejected while connected, or the VVM link drops when advertising starts): STOP and switch to the dual-adapter fallback in the spec before continuing.

- [ ] **Step 4: Commit**
```bash
git add requirements.txt tools/proxy_concurrency_spike.py
git commit -m "proxy: add bless dep + single-radio concurrency spike tool"
```

---

### Task 1: TrafficCapture

**Files:**
- Create: `vvm_to_signalk/traffic_capture.py`
- Test: `tests/test_traffic_capture.py`

**Interfaces:**
- Produces:
  - `class TrafficCapture(path: str, enabled: bool = True)`
  - `.record(direction: str, operation: str, uuid: str, data: bytes, now: datetime | None = None) -> None` — appends one line; `direction ∈ {"app->vvm","vvm->app"}`, `operation ∈ {"write","notify","read","subscribe"}`.
  - `.close() -> None`
  - Line format: `<iso8601> <direction> <operation> <uuid> <hex>\n` (hex empty string when `data` is empty).

- [ ] **Step 1: Write the failing test**

Create `tests/test_traffic_capture.py`:
```python
from datetime import datetime, timezone
from vvm_to_signalk.traffic_capture import TrafficCapture


def test_record_writes_one_line(tmp_path):
    path = tmp_path / "capture.log"
    cap = TrafficCapture(str(path))
    ts = datetime(2026, 7, 20, 1, 2, 3, tzinfo=timezone.utc)
    cap.record("app->vvm", "write", "00000001-0000-1000-8000-ec55f9f5b963",
               bytes.fromhex("a1b2"), now=ts)
    cap.close()
    line = path.read_text().strip()
    assert line == ("2026-07-20T01:02:03+00:00 app->vvm write "
                    "00000001-0000-1000-8000-ec55f9f5b963 a1b2")


def test_disabled_capture_writes_nothing(tmp_path):
    path = tmp_path / "capture.log"
    cap = TrafficCapture(str(path), enabled=False)
    cap.record("vvm->app", "notify", "x", b"\x01", now=datetime.now(timezone.utc))
    cap.close()
    assert not path.exists()


def test_empty_data_has_empty_hex(tmp_path):
    path = tmp_path / "capture.log"
    cap = TrafficCapture(str(path))
    ts = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)
    cap.record("app->vvm", "subscribe", "uuid", b"", now=ts)
    cap.close()
    assert path.read_text().strip().endswith("subscribe uuid ")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_traffic_capture.py -v`
Expected: FAIL with `ModuleNotFoundError: vvm_to_signalk.traffic_capture`.

- [ ] **Step 3: Write minimal implementation**

Create `vvm_to_signalk/traffic_capture.py`:
```python
"""Append-only capture of relayed BLE proxy traffic."""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class TrafficCapture:
    """Records every relayed GATT operation as one timestamped hex line."""

    def __init__(self, path: str, enabled: bool = True):
        self._enabled = enabled
        self._path = path
        self._fh = None
        if self._enabled:
            self._fh = open(path, "a", encoding="utf-8")  # noqa: SIM115

    def record(self, direction: str, operation: str, uuid: str, data: bytes,
               now: datetime | None = None) -> None:
        """Append one capture line. No-op when disabled."""
        if not self._enabled or self._fh is None:
            return
        ts = (now or datetime.now(timezone.utc)).isoformat()
        self._fh.write(f"{ts} {direction} {operation} {uuid} {data.hex()}\n")
        self._fh.flush()

    def close(self) -> None:
        """Close the capture file."""
        if self._fh is not None:
            self._fh.close()
            self._fh = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_traffic_capture.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**
```bash
git add vvm_to_signalk/traffic_capture.py tests/test_traffic_capture.py
git commit -m "proxy: TrafficCapture append-only relayed-traffic log"
```

---

### Task 2: ProxyConfig

**Files:**
- Create: `vvm_to_signalk/proxy_config.py`
- Test: `tests/test_proxy_config.py`

**Interfaces:**
- Produces:
  - `class ProxyConfig(data: dict | None = None)`
  - Properties: `.enabled: bool` (default False), `.capture_file: str` (default `./logs/ble_capture.log`), `.advertised_name: str | None` (default None → relay uses the ble-device name).
  - `.read(data: dict | None) -> None`
  - `.valid: bool` → True only when `.enabled` is True.

- [ ] **Step 1: Write the failing test**

Create `tests/test_proxy_config.py`:
```python
from vvm_to_signalk.proxy_config import ProxyConfig


def test_default_disabled_and_invalid():
    c = ProxyConfig()
    assert c.enabled is False
    assert c.valid is False
    assert c.capture_file == "./logs/ble_capture.log"
    assert c.advertised_name is None


def test_read_enables_and_overrides():
    c = ProxyConfig({"enabled": True, "capture-file": "/x/cap.log",
                     "advertised-name": "VVM_TEST"})
    assert c.enabled is True
    assert c.valid is True
    assert c.capture_file == "/x/cap.log"
    assert c.advertised_name == "VVM_TEST"


def test_read_none_is_noop():
    c = ProxyConfig()
    c.read(None)
    assert c.enabled is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_proxy_config.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `vvm_to_signalk/proxy_config.py`:
```python
"""Configuration for the BLE GATT proxy mode."""


class ProxyConfig:
    """Parses the optional `proxy` config section. Disabled by default."""

    def __init__(self, data: dict | None = None):
        self._enabled = False
        self._capture_file = "./logs/ble_capture.log"
        self._advertised_name = None
        if data is not None:
            self.read(data)

    def read(self, data: dict | None) -> None:
        """Read proxy settings from a dict; None is a no-op."""
        if data is None:
            return
        self._enabled = bool(data.get("enabled", self._enabled))
        self._capture_file = data.get("capture-file", self._capture_file)
        self._advertised_name = data.get("advertised-name", self._advertised_name)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def capture_file(self) -> str:
        return self._capture_file

    @property
    def advertised_name(self):
        return self._advertised_name

    @property
    def valid(self) -> bool:
        """The proxy is only 'valid' (should be constructed) when enabled."""
        return self._enabled
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_proxy_config.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**
```bash
git add vvm_to_signalk/proxy_config.py tests/test_proxy_config.py
git commit -m "proxy: ProxyConfig (opt-in, default off)"
```

---

### Task 3: GattProfileMirror

**Files:**
- Create: `vvm_to_signalk/gatt_mirror.py`
- Test: `tests/test_gatt_mirror.py`

**Interfaces:**
- Consumes: bleak's discovered `client.services` (a `BleakGATTServiceCollection`: iterable of services, each `.uuid` + `.characteristics`; each characteristic `.uuid` + `.properties` list of strings like `"read"`, `"write"`, `"notify"`, `"indicate"`, `"write-without-response"`).
- Produces:
  - `def mirror_profile(services) -> list[MirroredService]`
  - `@dataclass MirroredService: uuid: str; characteristics: list[MirroredChar]`
  - `@dataclass MirroredChar: uuid: str; properties: int; permissions: int` where `properties` is an OR of `bless.GATTCharacteristicProperties` flags and `permissions` an OR of `bless.GATTAttributePermissions`.
  - Mapping: bleak prop string → bless flag: `read→read, write→write, write-without-response→write_without_response, notify→notify, indicate→indicate`. Any `read` in props ⇒ `permissions |= readable`; any `write`/`write-without-response` ⇒ `permissions |= writeable`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gatt_mirror.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_gatt_mirror.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `vvm_to_signalk/gatt_mirror.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_gatt_mirror.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**
```bash
git add vvm_to_signalk/gatt_mirror.py tests/test_gatt_mirror.py
git commit -m "proxy: GattProfileMirror clones discovered GATT into bless specs"
```

---

### Task 4: BleDeviceConnection proxy hooks

**Files:**
- Modify: `vvm_to_signalk/ble_connection.py`
- Test: `tests/test_ble_proxy_hooks.py`

**Interfaces:**
- Consumes: existing `BleDeviceConnection`, `notification_handler(characteristic, data)`.
- Produces on `BleDeviceConnection`:
  - `set_notification_observer(cb: Callable[[str, bytes], None] | None) -> None` — registers a callback invoked with `(uuid, data)` for every notification, *in addition to* normal SignalK decoding. Set to `None` to clear.
  - `async proxy_write(uuid: str, data: bytes, response: bool = True) -> None` — writes to the connected VVM on the app's behalf; no-op (logged) if not connected.
  - `async proxy_read(uuid: str) -> bytes` — reads from the connected VVM; raises `RuntimeError("not connected")` if no client.
  - The connection stores the active `client` in `self._active_client` (None when disconnected) so the relay can drive writes/reads.
  - Fan-out is invoked at the *top* of `notification_handler` (before the early returns), so the observer sees fault/config/channel notifications alike.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ble_proxy_hooks.py`:
```python
import asyncio
from unittest.mock import AsyncMock

from vvm_to_signalk.ble_connection import BleDeviceConnection, BleConnectionConfig


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ble_proxy_hooks.py -v`
Expected: FAIL (`AttributeError: set_notification_observer`).

- [ ] **Step 3: Write minimal implementation**

In `vvm_to_signalk/ble_connection.py`, in `BleDeviceConnection.__init__` add near the other instance attrs:
```python
        self._active_client = None          # set while a BLE client is connected
        self._notification_observer = None  # proxy fan-out callback (uuid, data)
```

Add these methods to `BleDeviceConnection` (place them just after `accept_data_receiver`):
```python
    def set_notification_observer(self, callback) -> None:
        """Register a callback(uuid: str, data: bytes) invoked for every
        notification, in addition to normal decoding. None clears it.
        Used by the BLE proxy to forward the VVM stream to the native app."""
        self._notification_observer = callback

    async def proxy_write(self, uuid: str, data: bytes, response: bool = True) -> None:
        """Write to the connected VVM on the app's behalf (proxy mode)."""
        client = self._active_client
        if client is None:
            logger.warning("proxy_write dropped (no active VVM connection): %s", uuid)
            return
        await client.write_gatt_char(uuid, data, response=response)

    async def proxy_read(self, uuid: str) -> bytes:
        """Read a characteristic from the connected VVM (proxy mode)."""
        client = self._active_client
        if client is None:
            raise RuntimeError("not connected")
        return bytes(await client.read_gatt_char(uuid))
```

At the very top of `notification_handler`, before the `__last_message_time` line stays first, add the fan-out immediately after it:
```python
    def notification_handler(self, characteristic: BleakGATTCharacteristic, data: bytearray):
        """Handles BLE notifications and indications."""
        self.__last_message_time = asyncio.get_event_loop().time()
        observer = self._notification_observer
        if observer is not None:
            try:
                observer(characteristic.uuid, bytes(data))
            except Exception as e:  # never let the proxy break decoding
                logger.warning("notification observer error: %s", e)
        uuid = characteristic.uuid
        # ... existing body unchanged ...
```

In `_device_init_and_loop`, right after `connected = True` (line ~136), record the active client so the relay can drive it; and clear it in the `finally` block:
```python
                self._set_health(True, "Connected to device")
                connected = True
                self._active_client = client
                self._reset_unparsed_tracking()
```
and in the `finally:` of `_device_init_and_loop` add:
```python
        finally:
            self._active_client = None
            self._finalize_fault_subscribe_state()
            # ... existing finally body ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ble_proxy_hooks.py tests/test_blelogic.py -v`
Expected: new file PASS; `test_blelogic.py` still all PASS (no regression).

- [ ] **Step 5: Commit**
```bash
git add vvm_to_signalk/ble_connection.py tests/test_ble_proxy_hooks.py
git commit -m "proxy: notification fan-out + proxy_write/proxy_read hooks on central"
```

---

### Task 5: VvmProxyPeripheral

**Files:**
- Create: `vvm_to_signalk/proxy_peripheral.py`
- Test: `tests/test_proxy_peripheral.py`

**Interfaces:**
- Consumes: `MirroredService`/`MirroredChar` from `gatt_mirror`; a `bless.BlessServer` (constructed via an injectable factory for testing).
- Produces:
  - `class VvmProxyPeripheral(name: str, mirrored: list[MirroredService], on_write, on_read, server_factory=BlessServer)`
    - `on_write(uuid: str, data: bytes) -> None` — called when the app writes a char (relay forwards to VVM).
    - `on_read(uuid: str) -> bytes` — called when the app reads a char (relay returns cached/live VVM value).
  - `async start() -> None` — builds services/chars on the server, wires read/write callbacks, calls `server.start()` (begins advertising).
  - `async stop() -> None` — `server.stop()` (stops advertising / disconnects app).
  - `async push_notification(uuid: str, data: bytes) -> None` — sets the char value and calls `server.update_value(service_uuid, uuid)` so subscribed apps get the notification. Silently ignores unknown UUIDs.
  - Internally maps each char uuid → its service uuid for `update_value`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_proxy_peripheral.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_proxy_peripheral.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `vvm_to_signalk/proxy_peripheral.py`:
```python
"""bless GATT-server peripheral that emulates the VVM to the native app."""
import logging

from bless import BlessServer

logger = logging.getLogger(__name__)


class VvmProxyPeripheral:
    """Advertises a cloned VVM profile and relays app<->VVM via callbacks."""

    def __init__(self, name, mirrored, on_write, on_read, server_factory=BlessServer):
        self._name = name
        self._mirrored = mirrored
        self._on_write = on_write
        self._on_read = on_read
        self._server_factory = server_factory
        self._server = None
        self._char_to_service = {}

    async def start(self) -> None:
        """Build the cloned profile and begin advertising."""
        server = self._server_factory(name=self._name)
        server.read_request_func = self._handle_read
        server.write_request_func = self._handle_write
        for service in self._mirrored:
            await server.add_new_service(service.uuid)
            for char in service.characteristics:
                self._char_to_service[char.uuid] = service.uuid
                await server.add_new_characteristic(
                    service.uuid, char.uuid, char.properties,
                    bytearray(), char.permissions)
        await server.start()
        self._server = server
        logger.info("Proxy peripheral advertising as %s (%d chars)",
                    self._name, len(self._char_to_service))

    async def stop(self) -> None:
        """Stop advertising and disconnect the app."""
        if self._server is not None:
            await self._server.stop()
            self._server = None

    async def push_notification(self, uuid: str, data: bytes) -> None:
        """Deliver a VVM notification to a subscribed app."""
        if self._server is None:
            return
        service_uuid = self._char_to_service.get(uuid)
        if service_uuid is None:
            return
        char = self._server.get_characteristic(uuid)
        if char is None:
            return
        char.value = bytearray(data)
        self._server.update_value(service_uuid, uuid)

    def _handle_read(self, characteristic, **kwargs):
        """bless read callback: return the current value for the app."""
        try:
            return bytearray(self._on_read(characteristic.uuid))
        except Exception as e:
            logger.warning("proxy read error on %s: %s", characteristic.uuid, e)
            return bytearray()

    def _handle_write(self, characteristic, value, **kwargs):
        """bless write callback: forward the app's write to the VVM."""
        try:
            self._on_write(characteristic.uuid, bytes(value))
        except Exception as e:
            logger.warning("proxy write error on %s: %s", characteristic.uuid, e)
```

Note: bless calls `write_request_func(characteristic, value)`; the fake in the test calls it the same way. `read_request_func(characteristic)` returns the value.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_proxy_peripheral.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**
```bash
git add vvm_to_signalk/proxy_peripheral.py tests/test_proxy_peripheral.py
git commit -m "proxy: VvmProxyPeripheral bless GATT server with relay callbacks"
```

---

### Task 6: ProxyRelay (coordinator + advertising lifecycle)

**Files:**
- Create: `vvm_to_signalk/proxy_relay.py`
- Test: `tests/test_proxy_relay.py`

**Interfaces:**
- Consumes: `BleDeviceConnection` (`set_notification_observer`, `proxy_write`, `proxy_read`, `_active_client`), `mirror_profile`, `VvmProxyPeripheral`, `TrafficCapture`.
- Produces:
  - `class ProxyRelay(connection, proxy_config, advertised_name, loop, peripheral_factory=..., capture=None)`
  - `async on_upstream_ready(services) -> None` — mirror the profile, build+start the peripheral, register the notification observer. Called by the relay when the VVM link is up and streaming.
  - `async on_upstream_lost() -> None` — stop the peripheral, clear the observer.
  - `_forward_notification(uuid, data)` — observer body: capture + schedule `peripheral.push_notification` on the loop.
  - `_forward_write(uuid, data)` — peripheral on_write body: capture + schedule `connection.proxy_write` on the loop.
  - `_serve_read(uuid) -> bytes` — peripheral on_read body: returns last-cached notification value for `uuid` (dict updated by `_forward_notification`), else `b""`.
- The relay caches last-notified values per uuid for reads. Uses `asyncio.run_coroutine_threadsafe`/`loop.create_task` to bridge bless's callbacks to the async central.

- [ ] **Step 1: Write the failing test**

Create `tests/test_proxy_relay.py`:
```python
import asyncio

from vvm_to_signalk.proxy_config import ProxyConfig
from vvm_to_signalk.proxy_relay import ProxyRelay


class _FakeConn:
    def __init__(self):
        self.observer = None
        self.writes = []
    def set_notification_observer(self, cb):
        self.observer = cb
    async def proxy_write(self, uuid, data, response=True):
        self.writes.append((uuid, bytes(data)))


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


def _relay():
    conn = _FakeConn()
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_proxy_relay.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write minimal implementation**

Create `vvm_to_signalk/proxy_relay.py`:
```python
"""Coordinator wiring the VVM central to the app-facing peripheral."""
import asyncio
import logging

from .gatt_mirror import mirror_profile
from .proxy_peripheral import VvmProxyPeripheral

logger = logging.getLogger(__name__)


class ProxyRelay:
    """Relays notifications VVM->app and writes/reads app->VVM."""

    def __init__(self, connection, proxy_config, advertised_name, loop,
                 peripheral_factory=VvmProxyPeripheral, capture=None):
        self._conn = connection
        self._config = proxy_config
        self._name = advertised_name
        self._loop = loop
        self._peripheral_factory = peripheral_factory
        self._capture = capture
        self._peripheral = None
        self._read_cache = {}

    async def on_upstream_ready(self, services) -> None:
        """VVM link is up: clone the profile, advertise, start relaying."""
        mirrored = mirror_profile(services)
        self._peripheral = self._peripheral_factory(
            self._name, mirrored,
            on_write=self._forward_write,
            on_read=self._serve_read)
        await self._peripheral.start()
        self._conn.set_notification_observer(self._forward_notification)
        logger.info("Proxy relay active (advertising %s)", self._name)

    async def on_upstream_lost(self) -> None:
        """VVM link dropped: stop advertising and clear the relay."""
        self._conn.set_notification_observer(None)
        if self._peripheral is not None:
            await self._peripheral.stop()
            self._peripheral = None
        self._read_cache.clear()
        logger.info("Proxy relay stopped (upstream lost)")

    def _forward_notification(self, uuid, data):
        """Observer body (called from the central's notification path)."""
        self._read_cache[uuid] = bytes(data)
        if self._capture is not None:
            self._capture.record("vvm->app", "notify", uuid, bytes(data))
        peripheral = self._peripheral
        if peripheral is not None:
            self._loop.create_task(peripheral.push_notification(uuid, bytes(data)))

    def _forward_write(self, uuid, data):
        """Peripheral on_write body (called from bless callback thread/loop)."""
        if self._capture is not None:
            self._capture.record("app->vvm", "write", uuid, bytes(data))
        asyncio.run_coroutine_threadsafe(
            self._conn.proxy_write(uuid, bytes(data)), self._loop)

    def _serve_read(self, uuid) -> bytes:
        """Peripheral on_read body: last-known value for the char."""
        value = self._read_cache.get(uuid, b"")
        if self._capture is not None:
            self._capture.record("app->vvm", "read", uuid, value)
        return value
```

Note on the test: `test_app_write_forwarded_to_vvm` uses `run_coroutine_threadsafe` against the running loop; in the test the loop is running under `asyncio.run`, so the future is scheduled and executed on the next `await asyncio.sleep(0)`. If flaky under the test runner, the implementer may special-case "current loop" with `create_task`; keep the threadsafe path for the real bless callback which fires off-loop.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_proxy_relay.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**
```bash
git add vvm_to_signalk/proxy_relay.py tests/test_proxy_relay.py
git commit -m "proxy: ProxyRelay coordinator + read cache + capture wiring"
```

---

### Task 7: Wire proxy into config + main; advertising lifecycle from the central

**Files:**
- Modify: `vvm_to_signalk/vvm_monitor.py` (`VVMConfig.read`, add `proxy` property, `main()`)
- Modify: `vvm_to_signalk/ble_connection.py` (invoke relay `on_upstream_ready`/`on_upstream_lost`)
- Modify: `vvm_monitor.example.yaml`
- Test: `tests/test_vvm_monitor.py` (extend), `tests/test_blelogic.py` (no regression)

**Interfaces:**
- Consumes: `ProxyConfig`, `ProxyRelay`, `TrafficCapture`, `BleDeviceConnection`.
- Produces:
  - `VVMConfig.proxy -> ProxyConfig`; `VVMConfig.read` parses `data.get('proxy')`.
  - `BleDeviceConnection.set_proxy_relay(relay) -> None` — the connection calls `await relay.on_upstream_ready(client.services)` right after streaming is enabled + fault subscribe (end of the connect setup, line ~162), and `await relay.on_upstream_lost()` in the `finally`.
  - `main()`: when `config.proxy.valid`, build `TrafficCapture(config.proxy.capture_file)`, build `ProxyRelay(self.__ble_connection, config.proxy, name, loop, capture=capture)`, and `self.__ble_connection.set_proxy_relay(relay)`. `name` = `config.proxy.advertised_name or config.bluetooth.device_name`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_vvm_monitor.py`:
```python
def test_vvmconfig_reads_proxy_section():
    from vvm_to_signalk.vvm_monitor import VVMConfig
    cfg = VVMConfig({"proxy": {"enabled": True, "advertised-name": "VVM_X"}})
    assert cfg.proxy.enabled is True
    assert cfg.proxy.advertised_name == "VVM_X"


def test_vvmconfig_proxy_default_off():
    from vvm_to_signalk.vvm_monitor import VVMConfig
    cfg = VVMConfig({})
    assert cfg.proxy.enabled is False
```

Add to `tests/test_ble_proxy_hooks.py`:
```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_vvm_monitor.py::test_vvmconfig_reads_proxy_section tests/test_ble_proxy_hooks.py::test_set_proxy_relay_ready_and_lost_called -v`
Expected: FAIL (`proxy` attr / `set_proxy_relay` missing).

- [ ] **Step 3: Write minimal implementation**

In `vvm_to_signalk/vvm_monitor.py`:
- import: `from .proxy_config import ProxyConfig` and `from .proxy_relay import ProxyRelay` and `from .traffic_capture import TrafficCapture`.
- In `VVMConfig.__init__`: `self._proxy_config = ProxyConfig()`.
- In `VVMConfig.read`: add `self.proxy.read(data.get('proxy'))`.
- Add property:
```python
    @property
    def proxy(self):
        """Configuration for the BLE GATT proxy mode."""
        return self._proxy_config
```
- In `main()`, after the `self.__ble_connection` is created and receivers attached, before the TaskGroup:
```python
        if self.__ble_connection is not None and config.proxy.valid:
            loop = asyncio.get_event_loop()
            capture = TrafficCapture(config.proxy.capture_file)
            adv_name = config.proxy.advertised_name or config.bluetooth.device_name
            relay = ProxyRelay(self.__ble_connection, config.proxy, adv_name,
                               loop, capture=capture)
            self.__ble_connection.set_proxy_relay(relay)
            logger.info("BLE GATT proxy enabled (advertising as %s)", adv_name)
```

In `vvm_to_signalk/ble_connection.py`:
- In `__init__`: `self._proxy_relay = None`.
- Add methods:
```python
    def set_proxy_relay(self, relay) -> None:
        """Attach a ProxyRelay to mirror the VVM link to the native app."""
        self._proxy_relay = relay

    async def _proxy_notify_ready(self, services) -> None:
        if self._proxy_relay is not None:
            try:
                await self._proxy_relay.on_upstream_ready(services)
            except Exception as e:
                logger.warning("Proxy start failed (continuing without it): %s", e)

    async def _proxy_notify_lost(self) -> None:
        if self._proxy_relay is not None:
            try:
                await self._proxy_relay.on_upstream_lost()
            except Exception as e:
                logger.warning("Proxy stop error: %s", e)
```
- In `_device_init_and_loop`, right after `await self._subscribe_fault_alert(client)` (line ~162):
```python
                await self._subscribe_fault_alert(client)
                await self._proxy_notify_ready(client.services)
```
- In the `finally:` of `_device_init_and_loop`, before clearing `_active_client`:
```python
        finally:
            await self._proxy_notify_lost()
            self._active_client = None
            self._finalize_fault_subscribe_state()
            # ... existing finally body ...
```
(Note: the `finally` is now `async`-safe because `_device_init_and_loop` is already a coroutine.)

In `vvm_monitor.example.yaml`, add:
```yaml
# Optional: BLE GATT proxy so the native SmartCraft app can connect through
# this connector to the engine (the VVM only allows one BLE connection).
# Default: disabled. Requires an adapter that supports concurrent
# central+peripheral roles on one radio.
proxy:
  enabled: false
  # File that captures all relayed BLE traffic (timestamped hex).
  capture-file: ./logs/ble_capture.log
  # Name to advertise to the app. Defaults to ble-device.name when omitted.
  # advertised-name: "VVM_84FD27D92CBE"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_vvm_monitor.py tests/test_ble_proxy_hooks.py tests/test_blelogic.py -v`
Expected: all PASS (no regression in `test_blelogic.py`).

- [ ] **Step 5: Full suite + commit**

Run: `pytest -q`
Expected: all pass.
```bash
git add vvm_to_signalk/vvm_monitor.py vvm_to_signalk/ble_connection.py vvm_monitor.example.yaml tests/test_vvm_monitor.py tests/test_ble_proxy_hooks.py
git commit -m "proxy: wire ProxyRelay into config + connect/disconnect lifecycle"
```

---

### Task 8: End-to-end hardware validation (HARDWARE GATE)

**Files:** none (deploy + observe). Uses the boat per `boat-pi-deployment` memory.

**Interfaces:** validates the whole feature on real hardware before any release.

- [ ] **Step 1: Build a PR image**

Push the branch and open a PR so CI publishes `rgregg/vvm_monitor:pr-<N>` (multi-arch incl. arm64), per the existing `docker-pr-image.yml`. Do **not** touch `:1`.

- [ ] **Step 2: Deploy to the boat on the pr- image**

On the boat, back up compose, point `image:` at `rgregg/vvm_monitor:pr-<N>`, add a `proxy:` block with `enabled: true` to `config/vvm_monitor.yaml`, then:
```bash
docker compose pull vvm && docker compose up -d vvm
docker logs -f vvm_monitor
```
Expected log lines: `BLE GATT proxy enabled (advertising as VVM_...)`, then on connect `Proxy relay active (advertising VVM_...)`.

- [ ] **Step 3: End-to-end check (engine on)**

With the engine/VVM powered:
1. Confirm SignalK still updates: `curl -s http://localhost:3000/signalk/v1/api/vessels/self/propulsion | head`.
2. On the phone, open the native SmartCraft app; confirm `VVM_...` appears and connects **through the proxy**, and shows live engine data.
3. Confirm `logs/ble_capture.log` is populating with `app->vvm` and `vvm->app` lines.

- [ ] **Step 4: Indicate-subscribe check**

Watch for an upstream drop right after the app subscribes. In `ble_capture.log`, find the app's CCCD writes to `0x0301/0x0302/0x0401/0x2a05`. If the VVM link drops immediately after one, note which UUID; the follow-up is to stop forwarding that specific CCCD (add a deny-list in `_forward_write`). Record findings in the spec's "indicate-subscribe" section.

- [ ] **Step 5: Revert boat to stable, capture results**

Return the boat to `:1` (or leave on pr- for extended soak per user's call), and record the outcome (GO/partial/fallback-needed) in `docs/superpowers/specs/2026-07-20-ble-gatt-proxy-design.md`. If GO, cut a release and repoint per `boat-pi-deployment`.

---

## Self-Review

**Spec coverage:** single-radio (Task 0 gate), no-MAC-clone name advertising (Tasks 5/7), open GATT (no security anywhere), advertise-only-while-up (Tasks 6/7 lifecycle), capture (Tasks 1/6), GATT clone (Task 3), central independence for SignalK (unchanged init path), indicate-subscribe risk (Task 8 step 4 + deny-list follow-up), opt-in default-off (Tasks 2/7), `bless` dep (Task 0). All covered.

**Placeholder scan:** every code step has full code; commands have expected output; no TBD/TODO. The one deferred item (indicate deny-list) is explicitly a hardware-findings-driven follow-up, not a placeholder in shipped code.

**Type consistency:** `mirror_profile(services) -> list[MirroredService]` used in Task 6; `MirroredChar(uuid, properties, permissions)` consistent across Tasks 3/5; `set_notification_observer`/`proxy_write`/`proxy_read`/`set_proxy_relay` names consistent across Tasks 4/6/7; `on_write(uuid,data)`/`on_read(uuid)->bytes` consistent across Tasks 5/6; `push_notification(uuid,data)` consistent across Tasks 5/6.
