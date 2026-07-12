# Fault Alert (0x201) subscription + safe fallback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Subscribe to the Vessel View Mobile Fault Alert characteristic (`0x201`) so async engine faults reach the logs and SignalK, with an in-memory fallback that disables the subscription if it drops the BLE link.

**Architecture:** Add a targeted, isolated `0x201` indicate-subscription that runs *after* streaming is enabled (mirroring the native app's btsnoop-verified order). Guard it with two in-memory flags: `_fault_subscribe_disabled` (skip on subsequent connects this run) and `_fault_subscribe_pending` (in-flight marker for a backstop). A subscribe that raises — or a link drop that races the CCCD ack — disables faults for the rest of the process run while engine-data streaming continues; a container restart re-tries.

**Tech Stack:** Python 3, `bleak` (already a dependency — `start_notify` auto-selects indications for an indicate-only characteristic), `pytest`.

**Spec:** `docs/superpowers/specs/2026-07-10-fault-alert-subscription-design.md`

## Global Constraints

- `_setup_data_notifications` stays **notify-only**; never subscribe to `0x301`/`0x302`/`0x401`/`0x2a05`. Preserve `test_setup_data_notifications_skips_indicate_only`.
- Subscribe to `0x201` **after** `_set_streaming_mode(enabled=True)` (native-app order).
- Fallback state is **in-memory only** (no disk persistence). `_fault_subscribe_disabled` is set in `__init__` and never reset within `run()`, so a process restart re-tries.
- **Disable after 1** failed attempt (subscribe raises, or drop while pending).
- **No new dependencies.** Use the existing `bleak` client and `UUIDs.DEVICE_201_UUID`.
- The `0x201` decode path already exists (`notification_handler` → `_handle_fault_notification` → `parse_fault` → `accept_fault`); this plan only adds the missing subscription. Do not modify the decode path.

---

### Task 1: Fault-subscribe state + `_subscribe_fault_alert` helper

**Files:**
- Modify: `vvm_to_signalk/ble_connection.py` — `__init__` (add two flags); add `_subscribe_fault_alert` method
- Test: `tests/test_blelogic.py`

**Interfaces:**
- Produces:
  - Instance flags `self._fault_subscribe_disabled: bool` and `self._fault_subscribe_pending: bool`
  - `async def _subscribe_fault_alert(self, client) -> None` — subscribes to `UUIDs.DEVICE_201_UUID`; never raises; sets `_fault_subscribe_disabled` on failure; leaves `_fault_subscribe_pending` False on every return path that completes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_blelogic.py` (above the `if __name__ == "__main__":` block):

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_blelogic.py -k fault_alert -v`
Expected: FAIL — `AttributeError: 'BleDeviceConnection' object has no attribute '_subscribe_fault_alert'` (and `_fault_subscribe_disabled`).

- [ ] **Step 3: Add the state flags in `__init__`**

In `vvm_to_signalk/ble_connection.py`, find these lines in `__init__` (around line 39-41):

```python
        self._active_engine_ids = None   # set from data-item 10000
        self._last_active_ids = None     # set from runtime channel-map parse
        self._unparsed_seen = set()      # channel keys already warned about this connection
```

Add immediately after them:

```python
        # Fault Alert (0x201) subscription fallback state (in-memory, per process run).
        self._fault_subscribe_disabled = False  # set True after a subscribe drops the link
        self._fault_subscribe_pending = False   # True only between attempting and confirming
```

- [ ] **Step 4: Add the `_subscribe_fault_alert` helper**

In `vvm_to_signalk/ble_connection.py`, add this method immediately after `_request_offline_fault_channels` (i.e. right before `def notification_handler`, around line 257):

```python
    async def _subscribe_fault_alert(self, client):
        """Subscribe to Fault Alert (0x201) indications.

        The native app enables these indications *after* stream-start (verified
        from the btsnoop capture), so the caller invokes this after
        _set_streaming_mode. 0x201 is indicate-only; bleak.start_notify
        auto-selects indications. The CCCD write is an acknowledged ATT Write
        Request, so a device rejection (the #37 ATT 0x0e failure that drops the
        link) surfaces as an exception here. On any failure we disable fault
        subscription for the rest of this process run so engine-data streaming
        still works; a restart re-tries it.
        """
        if self._fault_subscribe_disabled:
            logger.info("Fault Alert (0x201) subscription disabled this run; skipping")
            return
        self._fault_subscribe_pending = True
        try:
            await client.start_notify(UUIDs.DEVICE_201_UUID, self.notification_handler)
        except Exception as e:
            logger.warning("Fault Alert (0x201) subscribe failed (%s); disabling "
                           "fault subscription for this run", e)
            self._fault_subscribe_disabled = True
            self._fault_subscribe_pending = False
            return
        logger.info("Subscribed to Fault Alert (0x201) indications")
        self._fault_subscribe_pending = False
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python3 -m pytest tests/test_blelogic.py -k fault_alert -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add vvm_to_signalk/ble_connection.py tests/test_blelogic.py
git commit -m "Add isolated Fault Alert (0x201) subscribe helper with disable-on-failure

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wire into the connect lifecycle + drop backstop

**Files:**
- Modify: `vvm_to_signalk/ble_connection.py` — `_device_init_and_loop` (call helper after streaming-enable; call backstop in `finally`); add `_finalize_fault_subscribe_state` method
- Test: `tests/test_blelogic.py`

**Interfaces:**
- Consumes: `_subscribe_fault_alert`, `_fault_subscribe_disabled`, `_fault_subscribe_pending` (Task 1)
- Produces: `def _finalize_fault_subscribe_state(self) -> None` — if `_fault_subscribe_pending` is still True, set `_fault_subscribe_disabled = True`; always clear `_fault_subscribe_pending`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_blelogic.py` (above the `if __name__ == "__main__":` block):

```python
def test_finalize_disables_when_pending():
    """If a connection ends mid-subscribe (drop raced the ack), the backstop
    attributes it to 0x201 and disables the subscription."""
    conn = _fresh_conn()
    conn._fault_subscribe_pending = True
    conn._finalize_fault_subscribe_state()
    assert conn._fault_subscribe_disabled is True
    assert conn._fault_subscribe_pending is False


def test_finalize_noop_when_not_pending():
    """A healthy session that disconnects later (pending already False) must not
    disable faults."""
    conn = _fresh_conn()
    conn._fault_subscribe_pending = False
    conn._fault_subscribe_disabled = False
    conn._finalize_fault_subscribe_state()
    assert conn._fault_subscribe_disabled is False


class Test_FaultSubscribeOrdering(unittest.IsolatedAsyncioTestCase):
    """The 0x201 subscribe must happen AFTER streaming is enabled (native-app order)."""

    async def test_subscribe_happens_after_streaming_enable(self):
        config = BleConnectionConfig()
        config.device_name = "UnitTestRunner"
        config.streaming_timeout = 0  # no monitor task -> no task_group needed
        conn = BleDeviceConnection(config, {})

        order = []

        async def noop(*_a, **_k):
            pass

        async def rec_stream(*_a, **_k):
            order.append("stream")

        async def rec_fault(*_a, **_k):
            order.append("fault")

        conn._retrieve_device_info = noop
        conn._initalize_vvm = noop
        conn._setup_data_notifications = noop
        conn._request_offline_fault_channels = noop
        conn._set_streaming_mode = rec_stream
        conn._subscribe_fault_alert = rec_fault

        class FakeClient:
            def __init__(self, device, disconnected_callback=None, timeout=None, **_kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_a):
                return False

        # Make the "await cancel_signal" return immediately.
        conn._BleDeviceConnection__cancel_signal.set_result(None)

        with patch("vvm_to_signalk.ble_connection.BleakClient", FakeClient):
            await conn._device_init_and_loop("fake-device")

        assert order == ["stream", "fault"], order
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/test_blelogic.py -k "finalize or FaultSubscribeOrdering" -v`
Expected: FAIL — `AttributeError: ... '_finalize_fault_subscribe_state'` for the finalize tests; the ordering test fails because `_device_init_and_loop` does not yet call `_subscribe_fault_alert` (`order == ["stream"]`).

- [ ] **Step 3: Add the `_finalize_fault_subscribe_state` method**

In `vvm_to_signalk/ble_connection.py`, add this method immediately after `_subscribe_fault_alert` (added in Task 1):

```python
    def _finalize_fault_subscribe_state(self):
        """Backstop for the fault-subscribe fallback: if a connection ended
        while a 0x201 subscribe was still in flight (a link drop raced the CCCD
        ack without raising in _subscribe_fault_alert), attribute the drop to
        the subscribe and disable it for the rest of this run."""
        if self._fault_subscribe_pending:
            logger.warning("Connection ended during Fault Alert (0x201) subscribe; "
                           "disabling fault subscription for this run")
            self._fault_subscribe_disabled = True
        self._fault_subscribe_pending = False
```

- [ ] **Step 4: Call the helper after streaming-enable**

In `_device_init_and_loop`, find (around line 143-144):

```python
                logger.info("Enabling data streaming from BLE device")
                await self._set_streaming_mode(client, enabled=True)
```

Insert immediately after it (before the `# Start the streaming monitor` block):

```python

                # Subscribe to Fault Alert (0x201) indications AFTER streaming is
                # enabled, mirroring the native app (btsnoop capture). Isolated so
                # a device that rejects it disables faults but keeps streaming.
                await self._subscribe_fault_alert(client)
```

- [ ] **Step 5: Call the backstop in `finally`**

In `_device_init_and_loop`, find the `finally` block (around line 158-161):

```python
        finally:
            if monitor_task:
                monitor_task.cancel()
            self.__cancel_signal = asyncio.Future()
```

Change it to call the backstop first:

```python
        finally:
            self._finalize_fault_subscribe_state()
            if monitor_task:
                monitor_task.cancel()
            self.__cancel_signal = asyncio.Future()
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `python3 -m pytest tests/test_blelogic.py -k "finalize or FaultSubscribeOrdering" -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Run the full suite (no regressions)**

Run: `python3 -m pytest -q`
Expected: PASS — all tests green (the pre-existing `DeprecationWarning: There is no current event loop` is unrelated and acceptable).

- [ ] **Step 8: Commit**

```bash
git add vvm_to_signalk/ble_connection.py tests/test_blelogic.py
git commit -m "Subscribe to Fault Alert (0x201) after streaming, with drop backstop

Wires the fault subscription into the connect lifecycle in native-app
order (after stream-start) and disables it if a connection drops while
the subscribe is still in flight.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Live validation on the boat (manual, post-merge)

**Not a code task.** Perform after Tasks 1-2 are merged to `main` and a `vX.Y.Z` tag is pushed (the boat's `:1` image updates only on a semver tag). See the boat deployment notes.

- [ ] **Step 1: Ship the image**

Merge `fault-visibility` to `main`, push a `vX.Y.Z` tag, then on the boat:

```bash
ssh ryan@boat-searayspx 'cd /opt/stacks/boatpi && docker compose pull vvm && docker compose up -d vvm'
```

- [ ] **Step 2: Confirm the subscribe succeeds and streaming stays up**

Watch several connect cycles:

```bash
ssh ryan@boat-searayspx 'tail -f /opt/stacks/boatpi/vvm/logs/vvm_monitor.log'
```

Expected: `Subscribed to Fault Alert (0x201) indications`, followed by continuous data (`Active engines: ...`, no `Device error` / disconnect loop). Confirm the CSV keeps growing (`data.csv`).

- [ ] **Step 3: Confirm the fallback (only if the device rejects 0x201)**

If instead you see `Fault Alert (0x201) subscribe failed (...); disabling fault subscription for this run`, confirm the *next* reconnect streams engine data normally and does not loop. This is the safe-degradation path; capture the exact error and stop — it means `0x201` indicate-subscribe is not safe on this firmware and the design's assumption needs revisiting.

- [ ] **Step 4: Confirm a real fault is captured**

When a fault is present (or next occurs), expect a `Fault received: Fault(...)` INFO line and a SignalK `notifications.propulsion.<engine>.vvmFault.<key>` delta. Human-readable text is not available offline (cloud-dependent, protocol-map §3.5) — code/position/active-state are.

---

## Notes for the implementer

- `UUIDs.DEVICE_201_UUID` already exists (`vvm_to_signalk/ble_connection.py`, in the `UUIDs` class) and is already used by `notification_handler`.
- Do **not** add `0x201` to `_setup_data_notifications`; it must stay notify-only. The whole point is that `0x201` is handled separately, after streaming.
- The ordering test patches `BleakClient` and stubs the sub-steps to record call order; it relies on `config.streaming_timeout = 0` so no `task_group` is needed, and resolves the private `__cancel_signal` future so the connect loop returns immediately.
