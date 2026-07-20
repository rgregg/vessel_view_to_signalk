# VVM Notification Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make VVM SignalK notifications quiet-by-default, reserving the audible alarm (`method` containing `"sound"`) for a small curated allowlist of engine-protection conditions.

**Architecture:** A new pure-logic module `notification_policy.py` decides a notification's `state` (`alarm` / `alert` / `normal`) from identifiers we understand, and maps `state → method`. The publisher stops hardcoding `alarm`+`sound` and instead asks the policy. The opaque 0–7 Universal-fault severity integer is never consulted.

**Tech Stack:** Python 3, `unittest` + plain `pytest`-style functions, `asyncio`. No new dependencies.

## Global Constraints

- No new third-party dependencies.
- Enum/flag label strings must match `vvm_to_signalk/data/smartcraft_data_items.json` verbatim (verified 2026-07-13): Guardian Cause causes are `GC_*`; Seven-Function Gauge flags include `Oil Fault`, `Water Pressure Fault`, `Coolant Temperature Fault`, `Guardian/Check Engine`.
- `state → method` mapping is the single source of truth: `alarm → ["visual","sound"]`, `alert → ["visual"]`, `warn → ["visual"]`, `normal → []`.
- Policy decision rule: active + on critical allowlist → `alarm`; active + not on allowlist → `alert`; inactive/cleared → `normal`.
- Critical seeds: Guardian = `{GC_CHI, GC_TEMPERATURE_HIGH, GC_BLK_PRESS_LOW, GC_LOW_OIL, GC_CRITICAL_OIL, GC_OIL_PRESSURE}`; bitfield = `{Oil Fault, Water Pressure Fault, Coolant Temperature Fault}`; faults = empty; MIL = not seeded (visual-only).
- Run the full suite with `python -m pytest -q` from the repo root.

---

### Task 1: `notification_policy` module

**Files:**
- Create: `vvm_to_signalk/notification_policy.py`
- Test: `tests/test_notification_policy.py`

**Interfaces:**
- Consumes: nothing (pure module, stdlib only).
- Produces:
  - `METHOD_BY_STATE: dict[str, list[str]]`
  - `is_critical(kind: str, key: str) -> bool` — `kind` ∈ {`"guardian"`, `"bitfield"`, `"fault"`, `"mil"`, …}; unknown kinds match nothing.
  - `state_for(kind: str, key: str, is_active: bool) -> str` — returns `"alarm"` | `"alert"` | `"normal"`.
  - `method_for(state: str) -> list[str]` — returns a fresh list; unknown state → `[]`.
  - Allowlist constants: `CRITICAL_GUARDIAN_CAUSES`, `CRITICAL_BITFIELD_FLAGS`, `CRITICAL_FAULT_KEYS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notification_policy.py`:

```python
"""Tests for the notification policy (quiet-by-default with a critical allowlist)."""

from vvm_to_signalk import notification_policy as np


def test_method_by_state_mapping():
    assert np.METHOD_BY_STATE["alarm"] == ["visual", "sound"]
    assert np.METHOD_BY_STATE["alert"] == ["visual"]
    assert np.METHOD_BY_STATE["warn"] == ["visual"]
    assert np.METHOD_BY_STATE["normal"] == []


def test_method_for_returns_fresh_copy():
    a = np.method_for("alarm")
    a.append("mutated")
    assert np.method_for("alarm") == ["visual", "sound"]  # not mutated


def test_method_for_unknown_state_is_empty():
    assert np.method_for("bogus") == []


def test_inactive_is_always_normal():
    assert np.state_for("guardian", "GC_CHI", False) == "normal"
    assert np.state_for("bitfield", "Oil Fault", False) == "normal"
    assert np.state_for("fault", "946-6", False) == "normal"


def test_active_critical_guardian_is_alarm():
    assert np.state_for("guardian", "GC_CHI", True) == "alarm"
    assert np.state_for("guardian", "GC_LOW_OIL", True) == "alarm"


def test_active_noncritical_guardian_is_alert():
    assert np.state_for("guardian", "GC_BREAKIN", True) == "alert"


def test_active_critical_bitfield_is_alarm():
    assert np.state_for("bitfield", "Coolant Temperature Fault", True) == "alarm"


def test_active_noncritical_bitfield_is_alert():
    assert np.state_for("bitfield", "Guardian/Check Engine", True) == "alert"


def test_faults_are_alert_empty_allowlist():
    assert np.state_for("fault", "1111-Legacy", True) == "alert"


def test_mil_kind_is_alert_when_active():
    assert np.state_for("mil", "MIL Constant On", True) == "alert"


def test_unknown_kind_is_alert_when_active():
    assert np.state_for("bogus", "whatever", True) == "alert"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_notification_policy.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'vvm_to_signalk.notification_policy'`

- [ ] **Step 3: Write the module**

Create `vvm_to_signalk/notification_policy.py`:

```python
"""Notification policy: decide a SignalK notification's ``state`` (and hence
whether it is an audible alarm or a silent visual notice) for VVM conditions.

Quiet by default: an active condition is a silent ``alert`` unless it appears on
a curated critical allowlist, in which case it is an audible ``alarm``. Cleared
conditions are ``normal``.

The opaque 0-7 Universal-fault severity integer is deliberately NOT consulted;
its meaning is cloud-resolved and unknown to this codebase. Policy keys off
identifiers we understand (Guardian Cause enum text, Seven-Function Gauge flag
names, and fault keys).
"""

# Single source of truth for how a state renders as a SignalK notification
# method. Clients (e.g. KIP) beep only when "sound" is present.
METHOD_BY_STATE = {
    "alarm": ["visual", "sound"],
    "alert": ["visual"],
    "warn": ["visual"],
    "normal": [],
}

# Guardian Cause (item 87) enum values that warrant an audible alarm: the
# overheat and oil-pressure engine-protection set.
CRITICAL_GUARDIAN_CAUSES = {
    "GC_CHI",
    "GC_TEMPERATURE_HIGH",
    "GC_BLK_PRESS_LOW",
    "GC_LOW_OIL",
    "GC_CRITICAL_OIL",
    "GC_OIL_PRESSURE",
}

# Seven-Function Gauge (item 97) bit flags that warrant an audible alarm.
CRITICAL_BITFIELD_FLAGS = {
    "Oil Fault",
    "Water Pressure Fault",
    "Coolant Temperature Fault",
}

# Universal/Legacy fault keys that warrant an audible alarm. Empty: fault
# identity is opaque, so every fault is visual-only until specific keys are
# curated in here.
CRITICAL_FAULT_KEYS: set = set()

_ALLOWLISTS = {
    "guardian": CRITICAL_GUARDIAN_CAUSES,
    "bitfield": CRITICAL_BITFIELD_FLAGS,
    "fault": CRITICAL_FAULT_KEYS,
}


def is_critical(kind: str, key: str) -> bool:
    """True if this condition should raise an audible alarm. Unknown kinds
    (e.g. "mil") match nothing and are therefore never critical."""
    return key in _ALLOWLISTS.get(kind, ())


def state_for(kind: str, key: str, is_active: bool) -> str:
    """Return the SignalK notification state for a condition.

    inactive -> "normal"; active + critical -> "alarm"; active otherwise ->
    "alert" (fail-quiet: anything we do not recognize stays silent)."""
    if not is_active:
        return "normal"
    return "alarm" if is_critical(kind, key) else "alert"


def method_for(state: str) -> list:
    """Return a fresh method list for a state; unknown state -> []."""
    return list(METHOD_BY_STATE.get(state, []))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notification_policy.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
git add vvm_to_signalk/notification_policy.py tests/test_notification_policy.py
git commit -m "Add notification policy: quiet-by-default state/method rules"
```

---

### Task 2: Derive `method` from state in `_send_notification`

**Files:**
- Modify: `vvm_to_signalk/signalk_publisher.py` (import; `_send_notification` at lines ~194–210)
- Test: `tests/test_signalk_publisher.py` (add one test)

**Interfaces:**
- Consumes: `method_for` from Task 1.
- Produces: no signature change; `_send_notification(path, state, message, extra=None)` now emits `method_for(state)`, adding the `alert → ["visual"]` case.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_signalk_publisher.py` (near the other module-level functions):

```python
def test_send_notification_alert_is_visual_only():
    p = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    ws = FakeWS(); p._SignalKPublisher__websocket = ws; p.socket_connected = True
    asyncio.run(p._send_notification("notifications.test.path", "alert", "hi"))
    v = ws.sent[0]["updates"][0]["values"][0]["value"]
    assert v["state"] == "alert"
    assert v["method"] == ["visual"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_signalk_publisher.py::test_send_notification_alert_is_visual_only -q`
Expected: FAIL — `assert [] == ["visual"]` (old code returns `[]` for non-`alarm` states).

- [ ] **Step 3: Update the import and `_send_notification`**

In `vvm_to_signalk/signalk_publisher.py`, extend the existing import from `signalk_mapping` line with a new import line beneath it (only `method_for` is used in this task; `state_for` is added by Task 3):

```python
from .signalk_mapping import signalk_path, to_si, engine_label, _camel
from .notification_policy import method_for
```

Then change the `value` dict inside `_send_notification` from:

```python
        value = {"state": state,
                 "method": ["visual", "sound"] if state == "alarm" else [],
                 "message": message}
```

to:

```python
        value = {"state": state,
                 "method": method_for(state),
                 "message": message}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_signalk_publisher.py -q`
Expected: PASS. Existing `alarm`/`normal` tests are unaffected (mapping is identical for those states); the new `alert` test now passes.

- [ ] **Step 5: Commit**

```bash
git add vvm_to_signalk/signalk_publisher.py tests/test_signalk_publisher.py
git commit -m "Derive notification method from state via policy"
```

---

### Task 3: Apply policy to the enum (87/106) and bitfield (97) paths

**Files:**
- Modify: `vvm_to_signalk/signalk_publisher.py` (`accept_engine_data` enum + bitfield branches, lines ~215–229; add `_GUARDIAN_CAUSE_ID` constant near line 12)
- Test: `tests/test_signalk_publisher.py` (update 2 tests, add 1)

**Interfaces:**
- Consumes: `state_for` from Task 1 (imported in this task).
- Produces: enum path passes `kind="guardian"` for item 87 and `kind="mil"` for item 106; bitfield path passes `kind="bitfield"` with the flag name.

- [ ] **Step 1: Update existing tests to the new expected behavior**

In `tests/test_signalk_publisher.py`, replace `test_seven_function_gauge_emits_per_flag` with a version that exercises a seed flag (bit 7, `Coolant Temperature Fault`) and a non-seed flag (bit 2, `Guardian/Check Engine`):

```python
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
    # bit 7 = Coolant Temperature Fault (critical), bit 2 = Guardian/Check Engine (not seeded)
    asyncio.run(p.accept_engine_data(D.by_id(97), 1, (1 << 7) | (1 << 2)))
    paths = {u["updates"][0]["values"][0]["path"]: u["updates"][0]["values"][0]["value"]
             for u in ws.sent}
    assert paths["notifications.propulsion.starboard.coolantTemperatureFault"]["state"] == "alarm"
    assert paths["notifications.propulsion.starboard.coolantTemperatureFault"]["method"] == ["visual", "sound"]
    assert paths["notifications.propulsion.starboard.guardianCheckEngine"]["state"] == "alert"
    assert paths["notifications.propulsion.starboard.guardianCheckEngine"]["method"] == ["visual"]
    assert paths["notifications.propulsion.starboard.oilFault"]["state"] == "normal"
```

Replace `test_mil_on_emits_alarm` with `test_mil_on_emits_alert`:

```python
def test_mil_on_emits_alert():
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
    assert v["value"]["state"] == "alert"
    assert v["value"]["method"] == ["visual"]
    assert v["value"]["message"].endswith("MIL Constant On")
```

Add a new test for a non-seed Guardian cause:

```python
def test_guardian_cause_noncritical_emits_alert():
    p = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    from vvm_to_signalk.data_dictionary import DataDictionary
    D = DataDictionary.load()

    class WS:
        def __init__(self): self.sent = []
        async def send(self, m): self.sent.append(json.loads(m))

    ws = WS()
    p._SignalKPublisher__websocket = ws
    p.socket_connected = True
    asyncio.run(p.accept_engine_data(D.by_id(87), 1, 7))  # GC_BREAKIN (not seeded)
    v = ws.sent[0]["updates"][0]["values"][0]["value"]
    assert v["state"] == "alert"
    assert v["method"] == ["visual"]
```

Note: `test_guardian_cause_active_emits_alarm` (value 4 = `GC_LOW_OIL`, seeded) and `test_guardian_cause_none_is_normal` (value 0) stay as-is — do not modify them.

- [ ] **Step 2: Run the updated tests to verify they fail**

Run: `python -m pytest tests/test_signalk_publisher.py -q`
Expected: FAIL — `test_seven_function_gauge_emits_per_flag`, `test_mil_on_emits_alert`, and `test_guardian_cause_noncritical_emits_alert` fail because the code still hardcodes `alarm`.

- [ ] **Step 3: Update the publisher branches**

In `vvm_to_signalk/signalk_publisher.py`, add `state_for` to the policy import so it reads:

```python
from .notification_policy import method_for, state_for
```

Then add a constant beneath the existing fault-id sets (line ~13):

```python
_OFFLINE_FAULT_IDS = {87, 106}     # enum-style single alarm (Guardian Cause, MIL)
_BITFIELD_FAULT_IDS = {97}         # one notification per bit (Seven Function Gauge)
_GUARDIAN_CAUSE_ID = 87            # enum path: distinguishes Guardian (87) from MIL (106)
```

Replace the enum branch:

```python
        if item.id in _OFFLINE_FAULT_IDS:
            text = item.render_enum(value) or str(int(value))
            inactive = int(value) == 0  # 0 == GC_NONE / MIL Off
            await self._send_notification(
                f"notifications.propulsion.{label}.{_camel(item.name)}",
                "normal" if inactive else "alarm",
                f"Engine {engine_id} {item.name}: {text}")
            return
```

with:

```python
        if item.id in _OFFLINE_FAULT_IDS:
            text = item.render_enum(value) or str(int(value))
            is_active = int(value) != 0  # 0 == GC_NONE / MIL Off
            kind = "guardian" if item.id == _GUARDIAN_CAUSE_ID else "mil"
            await self._send_notification(
                f"notifications.propulsion.{label}.{_camel(item.name)}",
                state_for(kind, text, is_active),
                f"Engine {engine_id} {item.name}: {text}")
            return
```

Replace the bitfield branch:

```python
        if item.id in _BITFIELD_FAULT_IDS:
            for flag_name, flag_val in item.render_bits(value).items():
                await self._send_notification(
                    f"notifications.propulsion.{label}.{_camel(flag_name)}",
                    "alarm" if flag_val else "normal",
                    f"Engine {engine_id} {flag_name}: {'active' if flag_val else 'clear'}")
            return
```

with:

```python
        if item.id in _BITFIELD_FAULT_IDS:
            for flag_name, flag_val in item.render_bits(value).items():
                await self._send_notification(
                    f"notifications.propulsion.{label}.{_camel(flag_name)}",
                    state_for("bitfield", flag_name, bool(flag_val)),
                    f"Engine {engine_id} {flag_name}: {'active' if flag_val else 'clear'}")
            return
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_signalk_publisher.py -q`
Expected: PASS (all publisher tests, including the two updated and one new).

- [ ] **Step 5: Commit**

```bash
git add vvm_to_signalk/signalk_publisher.py tests/test_signalk_publisher.py
git commit -m "Apply notification policy to Guardian/MIL/bitfield paths"
```

---

### Task 4: Route `accept_fault` through the policy and `_send_notification`

**Files:**
- Modify: `vvm_to_signalk/signalk_publisher.py` (`accept_fault`, lines ~246–272)
- Test: `tests/test_signalk_publisher.py` (update 1 test)

**Interfaces:**
- Consumes: `state_for` from Task 1; `_send_notification(path, state, message, extra=None)` from Task 2.
- Produces: no signature change to `accept_fault(self, fault)`. Faults now emit `state_for("fault", fault.fault_key, fault.is_active)` and gain change-only dedup.

- [ ] **Step 1: Update the existing test to the new expected behavior**

In `tests/test_signalk_publisher.py`, update `test_accept_fault_emits_notification` — a Legacy fault is not on the (empty) critical allowlist, so it is now a silent `alert`:

```python
def test_accept_fault_emits_notification():
    pub = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    ws = FakeWS()
    pub._SignalKPublisher__websocket = ws
    pub.socket_connected = True
    fault = Fault("Legacy", 1, True, 1111)
    asyncio.run(pub.accept_fault(fault))
    delta = ws.sent[0]["updates"][0]["values"][0]
    assert delta["path"] == "notifications.propulsion.starboard.vvmFault.1111-Legacy"
    assert delta["value"]["state"] == "alert"
    assert delta["value"]["method"] == ["visual"]
    assert delta["value"]["vvm"]["faultId"] == 1111
```

Note: `test_accept_fault_cleared_is_normal` (expects `normal` + `[]`) stays as-is, and the two message-content tests do not assert state, so they stay as-is.

- [ ] **Step 2: Run the updated test to verify it fails**

Run: `python -m pytest tests/test_signalk_publisher.py::test_accept_fault_emits_notification -q`
Expected: FAIL — `assert 'alarm' == 'alert'` (code still hardcodes `alarm`).

- [ ] **Step 3: Rewrite `accept_fault`**

Replace `accept_fault` in `vvm_to_signalk/signalk_publisher.py`:

```python
    async def accept_fault(self, fault):
        """Publish a fault as a SignalK notification delta."""
        label = engine_label(fault.engine_position, self.__config.engine_labels)
        path = f"notifications.propulsion.{label}.vvmFault.{fault.fault_key}"
        description = fault.description
        message = f"Engine {fault.engine_position} fault {fault.fault_key}"
        if description:
            message += f": {description}"
        if not fault.is_active:
            message += " cleared"
        value = {
            "state": "alarm" if fault.is_active else "normal",
            "method": ["visual", "sound"] if fault.is_active else [],
            "message": message,
            "vvm": {
                "faultId": fault.fault_id,
                "failureTypeId": fault.failure_type_id,
                "severity": fault.severity,
                "type": fault.fault_type,
                "description": description,
            },
        }
        if self.socket_connected:
            try:
                await self.__websocket.send(json.dumps(self.generate_delta(path, value)))
            except Exception as e:
                logger.warning("Error sending fault on websocket: %s", e)
```

with:

```python
    async def accept_fault(self, fault):
        """Publish a fault as a SignalK notification delta (quiet-by-default:
        faults are visual-only unless their key is on the critical allowlist)."""
        label = engine_label(fault.engine_position, self.__config.engine_labels)
        path = f"notifications.propulsion.{label}.vvmFault.{fault.fault_key}"
        description = fault.description
        message = f"Engine {fault.engine_position} fault {fault.fault_key}"
        if description:
            message += f": {description}"
        if not fault.is_active:
            message += " cleared"
        extra = {
            "faultId": fault.fault_id,
            "failureTypeId": fault.failure_type_id,
            "severity": fault.severity,
            "type": fault.fault_type,
            "description": description,
        }
        await self._send_notification(
            path,
            state_for("fault", fault.fault_key, fault.is_active),
            message,
            extra=extra)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_signalk_publisher.py -q`
Expected: PASS (updated `test_accept_fault_emits_notification`, plus the unchanged cleared/message tests).

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (entire test suite green).

- [ ] **Step 6: Commit**

```bash
git add vvm_to_signalk/signalk_publisher.py tests/test_signalk_publisher.py
git commit -m "Route accept_fault through notification policy (visual-only by default)"
```

---

## Notes for the implementer

- `accept_fault` previously sent a delta on every call. Routing it through `_send_notification` adds change-only dedup (keyed on the notification path, which includes `fault_key`): a fault re-reported with an unchanged state is no longer re-sent. This is intended.
- Do not consult `fault.severity` for policy — it is still published inside the `vvm` block for reference only.
- To make a fault audible later, add its `fault_key` (e.g. `"946-6"`) to `CRITICAL_FAULT_KEYS` in `notification_policy.py`; no publisher changes needed.
