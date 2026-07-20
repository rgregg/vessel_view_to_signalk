# Engine identity (UserVar reads) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Read the engine's SmartCraft identity strings (Software/Calibration/Serial/ECU-Serial IDs) over BLE for active engines, log them, and publish them to SignalK.

**Architecture:** Add a race-free paged UserVar string reader (a handler-fed accumulator on the `0x111` characteristic), a `_retrieve_engine_identity` step that runs right after `_initalize_vvm` (before streaming, matching the native app), and an `accept_engine_identity` receiver method (SignalKPublisher publishes; CsvWriter no-ops). Every read is best-effort and can never abort the connection.

**Tech Stack:** Python 3, `bleak` (existing), `pytest`.

**Spec:** `docs/superpowers/specs/2026-07-13-engine-identity-uservar-reads.md`

## Global Constraints

- **Best-effort:** every UserVar read and the whole identity step must be wrapped so a timeout/malformed/error case logs a warning and returns `None`/skips — it must **never** abort connect or prevent streaming.
- Identity reads run **after `_initalize_vvm`** and **before** `_setup_data_notifications`/streaming (native-app order; `0x111` notify is already enabled by `_initalize_vvm`).
- Read identity for **active engines only** (derived from the item-10000 response; default `{1}`).
- SignalK paths: `propulsion.<label>.vvm.<kind>` (string values), where `<kind>` is exactly one of `softwareId`, `calibrationId`, `serialNumber`, `ecuSerialNumber`.
- Item ids per engine E (1-based): Software `4000+(E-1)`, Calibration `4004+(E-1)`, Serial `4008+(E-1)`, ECU Serial `4012+(E-1)`.
- The paged reader is a **handler-fed accumulator** (race-free) and must not disturb the existing single-page `0x111` reads in `_initalize_vvm` (those run when no paged read is active).
- No new dependencies. `UUIDs.DEVICE_NEXT_UUID` is the `0x111` characteristic.

---

### Task 1: Paged UserVar string reader

**Files:**
- Modify: `vvm_to_signalk/ble_connection.py` — add `_paged_read` state in `__init__`; add `_read_uservar_string`, `_feed_paged_read`, `_decode_uservar_string`; route `0x111` pages to the accumulator when active
- Test: `tests/test_blelogic.py`

**Interfaces:**
- Produces:
  - `self._paged_read: dict | None` — active-read state `{"item_id", "buffer", "expected_len", "future"}`
  - `async def _read_uservar_string(self, client, item_id, timeout=5.0) -> str | None`
  - `def _feed_paged_read(self, data: bytes) -> None`
  - `@staticmethod _decode_uservar_string(raw: bytes) -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_blelogic.py` (above the `if __name__ == "__main__":` block). Reuse the existing `_fresh_conn()` and `FakeChar` helpers already in this file.

```python
NEXT_UUID = "00000111-0000-1000-8000-ec55f9f5b963"


def _page0(item_id, total_len, chunk):
    """Build a UserVar page-0 frame: [00][id:2 LE][msgType=01][len:2 LE][chunk]."""
    return (bytes([0x00]) + item_id.to_bytes(2, "little") + bytes([0x01])
            + total_len.to_bytes(2, "little") + chunk)


def test_decode_uservar_string_strips_nuls():
    from vvm_to_signalk.ble_connection import BleDeviceConnection
    assert BleDeviceConnection._decode_uservar_string(b"1.0.0.0\x00\x00") == "1.0.0.0"


def test_feed_paged_read_single_page():
    """A string that fits in page 0 resolves the future with exactly len bytes."""
    conn = _fresh_conn()
    fut = asyncio.get_event_loop().create_future()
    conn._paged_read = {"item_id": 4000, "buffer": bytearray(),
                        "expected_len": None, "future": fut}
    conn._feed_paged_read(_page0(4000, 5, b"ABCDE"))
    assert fut.done() and fut.result() == b"ABCDE"


def test_feed_paged_read_multi_page():
    """A string split across pages is reassembled from page 0 + continuations."""
    conn = _fresh_conn()
    fut = asyncio.get_event_loop().create_future()
    conn._paged_read = {"item_id": 4000, "buffer": bytearray(),
                        "expected_len": None, "future": fut}
    conn._feed_paged_read(_page0(4000, 10, b"ABCD"))   # 4 of 10 bytes
    assert not fut.done()
    conn._feed_paged_read(bytes([0x01]) + b"EFGH")      # +4 -> 8
    assert not fut.done()
    conn._feed_paged_read(bytes([0x02]) + b"IJ")        # +2 -> 10
    assert fut.done() and fut.result() == b"ABCDEFGHIJ"


def test_feed_paged_read_id_mismatch_resolves_none():
    """A page-0 whose item id doesn't match the request resolves None."""
    conn = _fresh_conn()
    fut = asyncio.get_event_loop().create_future()
    conn._paged_read = {"item_id": 4000, "buffer": bytearray(),
                        "expected_len": None, "future": fut}
    conn._feed_paged_read(_page0(9999, 5, b"ABCDE"))
    assert fut.done() and fut.result() is None


def test_read_uservar_string_end_to_end():
    """_read_uservar_string writes the request and returns the assembled string
    once the (faked) device feeds its pages."""
    conn = _fresh_conn()

    class FakeClient:
        def __init__(self, c):
            self._c = c
        async def write_gatt_char(self, uuid, data, response=True):
            # Device replies with a two-page "SW-12345" value (8 bytes).
            self._c._feed_paged_read(_page0(4000, 8, b"SW-1"))
            self._c._feed_paged_read(bytes([0x01]) + b"2345")

    result = asyncio.get_event_loop().run_until_complete(
        conn._read_uservar_string(FakeClient(conn), 4000))
    assert result == "SW-12345"


def test_paged_read_routed_from_notification_handler():
    """When a paged read is active, 0x111 notifications feed the accumulator
    instead of the futures path."""
    conn = _fresh_conn()
    fut = asyncio.get_event_loop().create_future()
    conn._paged_read = {"item_id": 4000, "buffer": bytearray(),
                        "expected_len": None, "future": fut}
    conn.notification_handler(FakeChar(NEXT_UUID), bytearray(_page0(4000, 3, b"XYZ")))
    assert fut.done() and fut.result() == b"XYZ"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_blelogic.py -k "uservar or paged_read" -v`
Expected: FAIL — `AttributeError: ... '_decode_uservar_string'` / `'_feed_paged_read'` / `'_read_uservar_string'`.

- [ ] **Step 3: Add the `_paged_read` state in `__init__`**

In `vvm_to_signalk/ble_connection.py`, find:

```python
        # Fault Alert (0x201) subscription fallback state (in-memory, per process run).
        self._fault_subscribe_disabled = False  # set True after a subscribe drops the link
        self._fault_subscribe_pending = False   # True only between attempting and confirming
```

Add immediately after:

```python
        # Active paged UserVar string read (protocol-map §4); None when idle.
        self._paged_read = None
```

- [ ] **Step 4: Add the reader/accumulator/decoder methods**

In `vvm_to_signalk/ble_connection.py`, add these three methods immediately before `def notification_handler`:

```python
    async def _read_uservar_string(self, client, item_id, timeout=5.0):
        """Read a UserVar string item (protocol-map §4) via the paged protocol.

        Writes the 3-byte request and lets notification_handler feed the reply
        pages into a per-read accumulator. Returns the decoded string, or None on
        timeout / malformed reply / id mismatch. Best-effort: never raises.
        """
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._paged_read = {"item_id": item_id, "buffer": bytearray(),
                            "expected_len": None, "future": future}
        try:
            req = bytes([item_id & 0xFF, (item_id >> 8) & 0xFF, 0x00])
            await client.write_gatt_char(UUIDs.DEVICE_NEXT_UUID, req, response=True)
            raw = await asyncio.wait_for(future, timeout)
        except Exception as e:
            logger.warning("UserVar read of item %s failed: %s", item_id, e)
            return None
        finally:
            self._paged_read = None
        if raw is None:
            return None
        return self._decode_uservar_string(raw)

    def _feed_paged_read(self, data: bytes):
        """Feed one 0x111 page into the active paged read (protocol-map §4):
        page 0 = [00][id:2 LE][msgType][len:2 LE][data...]; page N = [N][data...]."""
        pr = self._paged_read
        if pr is None:
            return
        future = pr["future"]
        if future.done():
            return
        page = data[0] if data else -1
        if page == 0:
            if len(data) < 6:
                future.set_result(None)
                return
            item_id = int.from_bytes(data[1:3], byteorder="little")
            if item_id != pr["item_id"]:
                future.set_result(None)
                return
            pr["expected_len"] = int.from_bytes(data[4:6], byteorder="little")
            pr["buffer"].extend(data[6:])
        else:
            pr["buffer"].extend(data[1:])
        if pr["expected_len"] is not None and len(pr["buffer"]) >= pr["expected_len"]:
            future.set_result(bytes(pr["buffer"][:pr["expected_len"]]))

    @staticmethod
    def _decode_uservar_string(raw: bytes) -> str:
        """Decode UserVar string bytes as ASCII, dropping trailing NULs/whitespace."""
        return raw.decode("ascii", errors="replace").rstrip("\x00").strip()
```

- [ ] **Step 5: Route 0x111 pages to the accumulator when a read is active**

In `notification_handler`, find:

```python
        # Config / UserVar exchanges are resolved via registered futures, not decoded
        # as channel data (avoids "unmatched data" noise on every engine notification).
        if uuid in (UUIDs.DEVICE_CONFIG_UUID, UUIDs.DEVICE_NEXT_UUID):
            self._trigger_event_listener(uuid, data, True)
            return
```

Replace with:

```python
        # Config / UserVar exchanges are resolved via registered futures, not decoded
        # as channel data (avoids "unmatched data" noise on every engine notification).
        if uuid in (UUIDs.DEVICE_CONFIG_UUID, UUIDs.DEVICE_NEXT_UUID):
            # An active paged UserVar string read consumes 0x111 pages directly.
            if self._paged_read is not None and uuid == UUIDs.DEVICE_NEXT_UUID:
                self._feed_paged_read(bytes(data))
                return
            self._trigger_event_listener(uuid, data, True)
            return
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_blelogic.py -k "uservar or paged_read" -v`
Expected: PASS (6 tests).

- [ ] **Step 7: Commit**

```bash
git add vvm_to_signalk/ble_connection.py tests/test_blelogic.py
git commit -m "Add race-free paged UserVar string reader (0x111)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `accept_engine_identity` receiver method

**Files:**
- Modify: `vvm_to_signalk/config_decoder.py` — add `accept_engine_identity` to the `EngineDataReceiver` Protocol
- Modify: `vvm_to_signalk/signalk_publisher.py` — implement `accept_engine_identity` (publish)
- Modify: `vvm_to_signalk/csv_writer.py` — implement `accept_engine_identity` (no-op)
- Test: `tests/test_signalk_publisher.py`, `tests/test_csv_writer.py`

**Interfaces:**
- Produces: `async def accept_engine_identity(self, engine_id: int, kind: str, value: str) -> None` on the receiver interface. `SignalKPublisher` publishes a delta at `propulsion.<label>.vvm.<kind>`; `CsvWriter` no-ops.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_signalk_publisher.py` (above `if __name__ == "__main__":` if present, else at end). It reuses the `FakeWS` class and `SignalKPublisher`/`SignalKConfig` imports already in the file.

```python
def test_accept_engine_identity_publishes_delta():
    pub = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    ws = FakeWS(); pub._SignalKPublisher__websocket = ws; pub.socket_connected = True
    asyncio.run(pub.accept_engine_identity(1, "softwareId", "8M0107498"))
    delta = ws.sent[0]["updates"][0]["values"][0]
    assert delta["path"] == "propulsion.starboard.vvm.softwareId"
    assert delta["value"] == "8M0107498"


def test_accept_engine_identity_not_connected_is_silent():
    pub = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    ws = FakeWS(); pub._SignalKPublisher__websocket = ws; pub.socket_connected = False
    asyncio.run(pub.accept_engine_identity(1, "serialNumber", "0V123456"))
    assert ws.sent == []
```

Append to `tests/test_csv_writer.py` a no-op test (the file already imports `asyncio`, `CsvWriter`, and `CsvWriterConfig` at module top):

```python
def test_accept_engine_identity_is_noop():
    """CSV writer ignores engine identity strings (not time-series)."""
    writer = CsvWriter(CsvWriterConfig({"enabled": False}))
    # Must not raise and must not write anything.
    asyncio.run(writer.accept_engine_identity(1, "softwareId", "X"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_signalk_publisher.py tests/test_csv_writer.py -k "engine_identity" -v`
Expected: FAIL — `AttributeError: ... 'accept_engine_identity'`.

- [ ] **Step 3: Add `accept_engine_identity` to the Protocol**

In `vvm_to_signalk/config_decoder.py`, find:

```python
    async def accept_fault(self, fault) -> None:
        ...

    def update_active_items(self, item_ids: list[int]) -> None:
        ...
```

Replace with:

```python
    async def accept_fault(self, fault) -> None:
        ...

    async def accept_engine_identity(self, engine_id: int, kind: str, value: str) -> None:
        ...

    def update_active_items(self, item_ids: list[int]) -> None:
        ...
```

- [ ] **Step 4: Implement in `SignalKPublisher`**

In `vvm_to_signalk/signalk_publisher.py`, find the end of `accept_fault` (the block ending):

```python
        if self.socket_connected:
            try:
                await self.__websocket.send(json.dumps(self.generate_delta(path, value)))
            except Exception as e:
                logger.warning("Error sending fault on websocket: %s", e)
```

Add this new method immediately after it (before the `class SignalKConfig` line):

```python
    async def accept_engine_identity(self, engine_id, kind, value):
        """Publish an engine identity string (Software/Calibration/Serial/ECU IDs)
        as a SignalK metadata delta at propulsion.<label>.vvm.<kind>."""
        label = engine_label(engine_id, self.__config.engine_labels)
        path = f"propulsion.{label}.vvm.{kind}"
        if self.socket_connected:
            try:
                await self.__websocket.send(json.dumps(self.generate_delta(path, value)))
            except Exception as e:
                logger.warning("Error sending engine identity on websocket: %s", e)
```

- [ ] **Step 5: Implement the no-op in `CsvWriter`**

In `vvm_to_signalk/csv_writer.py`, find:

```python
    async def accept_fault(self, fault) -> None:
        """No-op: CSV writer does not record fault notifications."""
```

Add immediately after it:

```python
    async def accept_engine_identity(self, engine_id: int, kind: str, value: str) -> None:
        """No-op: CSV writer does not record engine identity strings."""
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_signalk_publisher.py tests/test_csv_writer.py -k "engine_identity" -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add vvm_to_signalk/config_decoder.py vvm_to_signalk/signalk_publisher.py vvm_to_signalk/csv_writer.py tests/test_signalk_publisher.py tests/test_csv_writer.py
git commit -m "Add accept_engine_identity receiver method (SignalK publish + CSV no-op)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `_retrieve_engine_identity` step + wiring

**Files:**
- Modify: `vvm_to_signalk/ble_connection.py` — parse active engines from the item-10000 read in `_initalize_vvm`; add `_retrieve_engine_identity` + `_dispatch_engine_identity`; call it (wrapped) in `_device_init_and_loop`
- Test: `tests/test_blelogic.py`

**Interfaces:**
- Consumes: `_read_uservar_string` (Task 1); `accept_engine_identity` on receivers (Task 2); existing `self.__data_receivers`, `self._track_task`, `self._active_engine_ids`.
- Produces: `async def _retrieve_engine_identity(self, client) -> None`; `def _dispatch_engine_identity(self, engine_id, kind, value) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_blelogic.py` (above the `if __name__ == "__main__":` block):

```python
class _FakeIdentityReceiver:
    """Receiver that captures accept_engine_identity calls."""
    def __init__(self):
        self.calls = []
    async def accept_engine_identity(self, engine_id, kind, value):
        self.calls.append((engine_id, kind, value))


def test_retrieve_engine_identity_reads_four_items_and_dispatches():
    """For each active engine, reads Software/Calibration/Serial/ECU-Serial by the
    correct item ids and dispatches them to receivers."""
    conn = _fresh_conn()
    conn._active_engine_ids = {1}
    rx = _FakeIdentityReceiver()
    conn.accept_data_receiver(rx)
    reads = {4000: "SW1", 4004: "CAL1", 4008: "SER1", 4012: "ECU1"}

    async def fake_read(client, item_id, *a, **k):
        return reads.get(item_id)
    conn._read_uservar_string = fake_read

    loop = asyncio.get_event_loop()
    loop.run_until_complete(conn._retrieve_engine_identity(None))
    loop.run_until_complete(asyncio.sleep(0))  # let dispatch tasks run
    assert (1, "softwareId", "SW1") in rx.calls
    assert (1, "calibrationId", "CAL1") in rx.calls
    assert (1, "serialNumber", "SER1") in rx.calls
    assert (1, "ecuSerialNumber", "ECU1") in rx.calls


def test_retrieve_engine_identity_skips_missing_and_never_raises():
    """A read that returns None is skipped; the step does not raise."""
    conn = _fresh_conn()
    conn._active_engine_ids = {1}
    rx = _FakeIdentityReceiver()
    conn.accept_data_receiver(rx)

    async def fake_read(client, item_id, *a, **k):
        return None
    conn._read_uservar_string = fake_read

    loop = asyncio.get_event_loop()
    loop.run_until_complete(conn._retrieve_engine_identity(None))
    loop.run_until_complete(asyncio.sleep(0))
    assert rx.calls == []


def test_retrieve_engine_identity_defaults_to_engine_1():
    """With no known active engines, defaults to engine 1 (item ids 4000/4004/4008/4012)."""
    conn = _fresh_conn()
    conn._active_engine_ids = None
    seen = []

    async def fake_read(client, item_id, *a, **k):
        seen.append(item_id)
        return None
    conn._read_uservar_string = fake_read

    asyncio.get_event_loop().run_until_complete(conn._retrieve_engine_identity(None))
    assert seen == [4000, 4004, 4008, 4012]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_blelogic.py -k "retrieve_engine_identity" -v`
Expected: FAIL — `AttributeError: ... '_retrieve_engine_identity'`.

- [ ] **Step 3: Add `_retrieve_engine_identity` and `_dispatch_engine_identity`**

In `vvm_to_signalk/ble_connection.py`, add these two methods immediately before `def _reset_unparsed_tracking`:

```python
    async def _retrieve_engine_identity(self, client):
        """Read engine identity strings (Software/Calibration/Serial/ECU-Serial IDs)
        for active engines via UserVar (protocol-map §4), log them, and dispatch to
        receivers. Best-effort: individual reads that fail are skipped."""
        bases = (("softwareId", 4000), ("calibrationId", 4004),
                 ("serialNumber", 4008), ("ecuSerialNumber", 4012))
        engines = sorted(self._active_engine_ids) if self._active_engine_ids else [1]
        for engine_id in engines:
            for kind, base in bases:
                item_id = base + (engine_id - 1)
                value = await self._read_uservar_string(client, item_id)
                if not value:
                    continue
                logger.info("Engine %s %s: %s", engine_id, kind, value)
                self._dispatch_engine_identity(engine_id, kind, value)

    def _dispatch_engine_identity(self, engine_id, kind, value):
        """Dispatch one engine identity value to all registered receivers."""
        loop = asyncio.get_event_loop()
        for receiver in self.__data_receivers:
            self._track_task(loop.create_task(
                receiver.accept_engine_identity(engine_id, kind, value)))
```

Note: `self.__data_receivers` inside the class resolves to the name-mangled attribute already used by `_publish_engine_value`.

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `python3 -m pytest tests/test_blelogic.py -k "retrieve_engine_identity" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Parse active engines from the item-10000 read**

In `_initalize_vvm`, find:

```python
        data = bytes([0x10, 0x27, 0x0])
        result = await self._request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        if (expected_result := '00102701010001') != result.hex():
            logger.warning("configuration_data_1 response: %s, expected: 00102701010001", result.hex())
```

Replace with:

```python
        data = bytes([0x10, 0x27, 0x0])
        result = await self._request_configuration_data(client, UUIDs.DEVICE_NEXT_UUID, data)
        if (expected_result := '00102701010001') != result.hex():
            logger.warning("configuration_data_1 response: %s, expected: 00102701010001", result.hex())
        # Response is a UserVar page-0 frame for item 10000 (Active Engines); the
        # engine bitfield is the payload byte at index 6. Capture it so the engine
        # identity reads target the right engines before streaming begins.
        if len(result) >= 7:
            bits = result[6]
            self._active_engine_ids = {e for e in (1, 2, 3, 4) if bits & (1 << (e - 1))}
```

- [ ] **Step 6: Wire the (wrapped) identity step into the connect sequence**

In `_device_init_and_loop`, find:

```python
                logger.info("Initalizing VVM...")
                await self._initalize_vvm(client)

                logger.info("Configuring data streaming notifications...")
                await self._setup_data_notifications(client)
```

Replace with:

```python
                logger.info("Initalizing VVM...")
                await self._initalize_vvm(client)

                # Best-effort engine identity read (Software/Calibration/Serial IDs).
                # Runs before streaming, matching the app; must never abort the connect.
                try:
                    await self._retrieve_engine_identity(client)
                except Exception as e:
                    logger.warning("Engine identity read step failed: %s", e)

                logger.info("Configuring data streaming notifications...")
                await self._setup_data_notifications(client)
```

- [ ] **Step 7: Run the full suite (no regressions)**

Run: `python3 -m pytest -q`
Expected: PASS — all tests green (the pre-existing `DeprecationWarning: There is no current event loop` is unrelated and acceptable).

- [ ] **Step 8: Commit**

```bash
git add vvm_to_signalk/ble_connection.py tests/test_blelogic.py
git commit -m "Read engine identity (UserVar) after init and publish it

Parses active engines from the item-10000 response, reads
Software/Calibration/Serial/ECU-Serial IDs for each active engine before
streaming (matching the app), logs and dispatches them. Best-effort:
wrapped so a failure never aborts connect or streaming.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Live validation on the boat (manual, post-merge)

**Not a code task.** After Tasks 1-3 merge and a `vX.Y.Z` tag ships `:1`, on the boat (VVM on):

- [ ] **Step 1: Deploy**

```bash
ssh ryan@boat-searayspx 'cd /opt/stacks/boatpi && docker compose pull vvm && docker compose up -d vvm'
```

- [ ] **Step 2: Confirm identity is captured and streaming is undisturbed**

```bash
ssh ryan@boat-searayspx 'sleep 40; grep -iE "Software Id|Calibration|Serial|Engine 1 " /opt/stacks/boatpi/vvm/logs/vvm_monitor.log | tail; tail -n 5 /opt/stacks/boatpi/vvm/logs/vvm_monitor.log'
```

Expected: `Engine 1 softwareId: <value>` (and the other kinds) appear once per connect, streaming (`Active engines: [1]`) continues, no `Device error`/disconnect loop. Optionally confirm SignalK: `curl -s http://localhost:3000/signalk/v1/api/vessels/self/propulsion/port/vvm`. Record the Software ID — it identifies the engine/ECM for picking the correct fault-code document.

---

## Notes for the implementer

- `UUIDs.DEVICE_NEXT_UUID` = `"00000111-0000-1000-8000-ec55f9f5b963"`, already defined in the `UUIDs` class.
- The existing single-page `0x111` reads in `_initalize_vvm` use `_request_configuration_data` and run when `self._paged_read is None`, so the accumulator routing added in Task 1 does not affect them.
- `engine_label` is a module-level function already imported/used in `signalk_publisher.py` (see `accept_fault`); engine 1 with default config maps to `starboard` (as the existing fault tests assert).
- Run tests from the repo root with `python3 -m pytest`. Deps are already installed on the host.
