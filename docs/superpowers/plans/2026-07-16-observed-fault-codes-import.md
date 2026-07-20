# Import Observed Fault Codes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import the 8 fault codes Ryan recorded from the native app as rich offline text (title + advisory) and make the four genuinely-critical codes audible.

**Architecture:** Extend the inline `FAULT_TEXT` map in `fault_decoder.py` from `{key: str}` to `{key: FaultText(title, advisory)}`; expose `Fault.description` (title) and a new `Fault.advisory`; carry advisory into the publisher's `vvm` block; seed the previously-empty `CRITICAL_FAULT_KEYS` so the existing policy makes those four faults `alarm`+sound. No policy-logic change.

**Tech Stack:** Python 3, stdlib `collections.namedtuple`, `unittest`/pytest-style tests, `asyncio`. No new dependencies.

## Global Constraints

- No new third-party dependencies.
- Test command: `python3 -m pytest -q` (bare `python` fails — pyenv 3.13.5 pin). Baseline before this plan: 160 passing.
- Fault codes are Universal `fault_key`s (`"<fault_id>-<failure_type_id>"`), keyed directly.
- Text model is **title + advisory** (drop the app's Line 2). Strings stored as ASCII (`O2`, `-`). `946-6` has no advisory (`None`).
- Rendering: title in the notification message (unchanged shape `"Engine N fault {key}: {title}"`), advisory in the `vvm` block.
- Audible (critical) set is exactly `{"1104-21", "1109-23", "3061-16", "4602-23"}`.
- The 8 codes and their exact text are the table in Task 1 — copy verbatim.

---

### Task 1: Fault text data model (title + advisory)

**Files:**
- Modify: `vvm_to_signalk/fault_decoder.py` (FAULT_TEXT + `namedtuple` + `description`/`advisory`)
- Test: `tests/test_fault_decoder.py` (new cases)
- Test: `tests/test_signalk_publisher.py` (update one existing test for the new `946-6` title)

**Interfaces:**
- Consumes: nothing new.
- Produces: `FaultText = namedtuple("FaultText", ["title", "advisory"])`; `FAULT_TEXT: dict[str, FaultText]`; `Fault.description -> str | None` (returns title); `Fault.advisory -> str | None`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_fault_decoder.py` (it already imports `Fault`):

```python
def test_known_fault_title_and_advisory():
    f = Fault("Universal", 1, True, 1109, failure_type_id=23)
    assert f.description == "Emergency stop"
    assert f.advisory.startswith("Check lanyard")


def test_known_fault_without_advisory():
    f = Fault("Universal", 1, True, 946, failure_type_id=6)
    assert f.description == "Catalyst oxygen storage capacity (starboard)"
    assert f.advisory is None


def test_unknown_fault_has_no_text():
    f = Fault("Legacy", 1, True, 1111)
    assert f.description is None
    assert f.advisory is None
```

Also update the existing `test_accept_fault_message_includes_known_description` in `tests/test_signalk_publisher.py` to the new `946-6` title (Task 1's text change alters it):

```python
def test_accept_fault_message_includes_known_description():
    pub = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    ws = FakeWS(); pub._SignalKPublisher__websocket = ws; pub.socket_connected = True
    asyncio.run(pub.accept_fault(Fault("Universal", 1, True, 946, failure_type_id=6)))
    delta = ws.sent[0]["updates"][0]["values"][0]
    assert "Catalyst oxygen storage capacity (starboard)" in delta["value"]["message"]
    assert "946-6" in delta["value"]["message"]
    assert delta["value"]["vvm"]["description"] == "Catalyst oxygen storage capacity (starboard)"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_fault_decoder.py -q`
Expected: FAIL — `AttributeError: 'Fault' object has no attribute 'advisory'` (and title mismatch on `946-6`).

- [ ] **Step 3: Update `fault_decoder.py`**

Replace the top-of-file import and `FAULT_TEXT` block (currently lines ~2 and ~7-14):

Change the import line:

```python
import logging
```

to:

```python
import logging
from collections import namedtuple
```

Replace the `FAULT_TEXT` comment + dict with:

```python
FaultText = namedtuple("FaultText", ["title", "advisory"])

# Offline fault text recorded from the native SmartCraft app. Mercury resolves
# fault text through a cloud API (protocol-map.md §3.5) with no offline
# dictionary, so this is a hand-maintained map of Universal codes keyed by
# `fault_key` = "<fault_id>-<failure_type_id>". `title` is shown in the
# notification message; `advisory` (the app's actionable Line-3 text) is carried
# in the SignalK vvm block and is None when the app shows none. Unknown codes
# fall back to the bare key.
FAULT_TEXT = {
    "946-6": FaultText("Catalyst oxygen storage capacity (starboard)", None),
    "1104-21": FaultText(
        "Drive lube",
        "Drive lube is low. Continued operation may cause damage."),
    "3151-16": FaultText(
        "Malfunction indicator lamp",
        "Malfunction indicator lamp is not working properly."),
    "1109-23": FaultText(
        "Emergency stop",
        "Check lanyard - key engine off and restart. If condition persists, "
        "service engine soon."),
    "4602-23": FaultText(
        "Fault blocker system voltage",
        "Return to port immediately - turn off unnecessary loads and check "
        "battery connections. Service engine before next use."),
    "3061-16": FaultText(
        "Fuel pump",
        "Fuel pump is not working properly. Return to port immediately - "
        "service engine before next use."),
    "842-16": FaultText(
        "Wideband O2 sensor heater - starboard bank (S1)",
        "Exhaust oxygen sensor is not working properly."),
    "822-16": FaultText(
        "Wideband O2 sensor heater - port bank (S1)",
        "Exhaust oxygen sensor is not working properly."),
}
```

Replace the existing `description` property:

```python
    @property
    def description(self) -> str | None:
        """Human-readable text for this fault code, or None if not in FAULT_TEXT."""
        return FAULT_TEXT.get(self.fault_key)
```

with:

```python
    @property
    def description(self) -> str | None:
        """Title text for this fault code, or None if not in FAULT_TEXT."""
        entry = FAULT_TEXT.get(self.fault_key)
        return entry.title if entry else None

    @property
    def advisory(self) -> str | None:
        """Actionable advisory text for this fault code, or None."""
        entry = FAULT_TEXT.get(self.fault_key)
        return entry.advisory if entry else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_fault_decoder.py tests/test_signalk_publisher.py -q`
Expected: PASS (new fault_decoder cases + the updated publisher description test).

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all green (163 passed).

- [ ] **Step 6: Commit**

```bash
git add vvm_to_signalk/fault_decoder.py tests/test_fault_decoder.py tests/test_signalk_publisher.py
git commit -m "Import observed fault text (title + advisory) into FAULT_TEXT"
```

---

### Task 2: Carry advisory into the publisher's vvm block

**Files:**
- Modify: `vvm_to_signalk/signalk_publisher.py` (`accept_fault` extra dict, ~lines 260-266)
- Test: `tests/test_signalk_publisher.py` (new case + one assertion added)

**Interfaces:**
- Consumes: `Fault.advisory` (Task 1).
- Produces: the fault notification's `value["vvm"]` now includes an `"advisory"` key.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_signalk_publisher.py`:

```python
def test_accept_fault_includes_advisory_in_vvm():
    pub = SignalKPublisher(SignalKConfig({"websocket-url": "ws://x"}), {})
    ws = FakeWS(); pub._SignalKPublisher__websocket = ws; pub.socket_connected = True
    asyncio.run(pub.accept_fault(Fault("Universal", 1, True, 1104, failure_type_id=21)))
    v = ws.sent[0]["updates"][0]["values"][0]["value"]
    assert v["vvm"]["advisory"].startswith("Drive lube is low")
```

Also extend `test_accept_fault_message_bare_code_when_unknown` (unknown code → no advisory) by adding one assertion after the existing `vvm.description is None` check:

```python
    assert delta["value"]["vvm"]["advisory"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_signalk_publisher.py -q`
Expected: FAIL — `KeyError: 'advisory'` (the vvm block has no advisory key yet).

- [ ] **Step 3: Add advisory to the extra dict**

In `vvm_to_signalk/signalk_publisher.py` `accept_fault`, change the `extra` dict from:

```python
        extra = {
            "faultId": fault.fault_id,
            "failureTypeId": fault.failure_type_id,
            "severity": fault.severity,
            "type": fault.fault_type,
            "description": description,
        }
```

to:

```python
        extra = {
            "faultId": fault.fault_id,
            "failureTypeId": fault.failure_type_id,
            "severity": fault.severity,
            "type": fault.fault_type,
            "description": description,
            "advisory": fault.advisory,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_signalk_publisher.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all green (164 passed).

- [ ] **Step 6: Commit**

```bash
git add vvm_to_signalk/signalk_publisher.py tests/test_signalk_publisher.py
git commit -m "Carry fault advisory text into the SignalK vvm block"
```

---

### Task 3: Seed critical fault keys + consistency guard

**Files:**
- Modify: `vvm_to_signalk/notification_policy.py` (`CRITICAL_FAULT_KEYS`)
- Test: `tests/test_notification_policy.py` (rename + extend the fault test)
- Test: `tests/test_fault_policy_matrix.py` (audible-fault case + text/keys consistency guard)

**Interfaces:**
- Consumes: `state_for("fault", key, is_active)` (unchanged); `FAULT_TEXT` (Task 1); `CRITICAL_FAULT_KEYS`.
- Produces: `CRITICAL_FAULT_KEYS = {"1104-21", "1109-23", "3061-16", "4602-23"}`.

- [ ] **Step 1: Write / update the failing tests**

In `tests/test_notification_policy.py`, replace `test_faults_are_alert_empty_allowlist` with:

```python
def test_faults_policy_by_allowlist():
    # Non-critical / unknown fault keys stay silent alert when active.
    assert np.state_for("fault", "1111-Legacy", True) == "alert"
    assert np.state_for("fault", "946-6", True) == "alert"
    # Seeded critical codes are audible alarms.
    assert np.state_for("fault", "1109-23", True) == "alarm"
    assert np.state_for("fault", "4602-23", True) == "alarm"
```

In `tests/test_fault_policy_matrix.py`, extend the notification_policy import to add `CRITICAL_FAULT_KEYS`, add a `FAULT_TEXT` import, and add two tests. Change the import block:

```python
from vvm_to_signalk.notification_policy import (
    CRITICAL_GUARDIAN_CAUSES,
    CRITICAL_BITFIELD_FLAGS,
)
```

to:

```python
from vvm_to_signalk.notification_policy import (
    CRITICAL_GUARDIAN_CAUSES,
    CRITICAL_BITFIELD_FLAGS,
    CRITICAL_FAULT_KEYS,
)
from vvm_to_signalk.fault_decoder import FAULT_TEXT
```

Add these two tests at the end of the file:

```python
def test_universal_critical_fault_is_audible():
    pub, ws = _fresh_pub()
    asyncio.run(pub.accept_fault(Fault("Universal", 1, True, 1109, failure_type_id=23)))
    v = _delta_ending(ws, "vvmFault.1109-23")
    assert v["state"] == "alarm"
    assert v["method"] == ["visual", "sound"]


def test_critical_fault_keys_have_text():
    # Every audible fault code must have known offline text (catches a typo in
    # either the allowlist or FAULT_TEXT).
    missing = CRITICAL_FAULT_KEYS - set(FAULT_TEXT)
    assert not missing, f"critical fault keys missing text: {missing}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_notification_policy.py tests/test_fault_policy_matrix.py -q`
Expected: FAIL — `test_faults_policy_by_allowlist` and `test_universal_critical_fault_is_audible` fail because `1109-23`/`4602-23` currently classify as `alert` (empty allowlist). (`test_critical_fault_keys_have_text` passes vacuously for now.)

- [ ] **Step 3: Seed the critical fault keys**

In `vvm_to_signalk/notification_policy.py`, change:

```python
CRITICAL_FAULT_KEYS: set = set()
```

to:

```python
# Universal fault codes (fault_key) recorded as critical in the native app.
CRITICAL_FAULT_KEYS: set = {"1104-21", "1109-23", "3061-16", "4602-23"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_notification_policy.py tests/test_fault_policy_matrix.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest -q`
Expected: all green (166 passed).

- [ ] **Step 6: Commit**

```bash
git add vvm_to_signalk/notification_policy.py tests/test_notification_policy.py tests/test_fault_policy_matrix.py
git commit -m "Seed critical fault keys from observed app codes + text guard"
```

---

## Notes for the implementer

- Frame counts in "Expected: N passed" are approximate; what matters is the named new/updated tests pass and nothing previously green breaks.
- `1104-21` (Drive lube) is on the audible set even though its category isn't literally "Critical" — its advisory warns of engine damage; this is intentional (per the design decision), not an error.
- Do not change the message *shape* in `accept_fault` — `description` still supplies the title, so `"Engine N fault {key}: {title}"` continues to work unchanged; Task 2 only adds the `vvm.advisory` field.
- The `description` property deliberately returns the **title** (not a combined string) to preserve the existing message/`vvm.description` contract.
