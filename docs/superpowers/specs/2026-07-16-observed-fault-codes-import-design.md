# Import Observed Fault Codes: Offline Text + Critical Seeds

Date: 2026-07-16
Status: Approved (design)

## Problem

Ryan went through the native SmartCraft app and recorded the fault codes and
messages he has actually seen, in a spreadsheet. This is the offline
code -> text source the connector has lacked. Today `FAULT_TEXT` in
`fault_decoder.py` has a single entry, so almost every fault surfaces as a bare
code (e.g. `1109-23`), and `CRITICAL_FAULT_KEYS` in `notification_policy.py` is
empty, so every Universal/Legacy fault is a silent `alert` — nothing beeps.

The sheet gives us both: human text for 8 codes, and (via its Category column)
which of them are genuinely critical.

## Source data (from the sheet, cleaned)

The `Code` column is the connector's Universal `fault_key`
(`fault_id-failure_type_id`). `Title` and Line 3 ("advisory", the actionable
"what to do" text) are kept; Line 2 is generic boilerplate and is dropped.
Codes are treated as Universal keys directly.

| fault_key | Title | Advisory (Line 3) | Audible? |
|-----------|-------|-------------------|----------|
| 946-6   | Catalyst oxygen storage capacity (starboard) | (none) | no |
| 1104-21 | Drive lube | Drive lube is low. Continued operation may cause damage. | **yes** |
| 3151-16 | Malfunction indicator lamp | Malfunction indicator lamp is not working properly. | no |
| 1109-23 | Emergency stop | Check lanyard - key engine off and restart. If condition persists, service engine soon. | **yes** |
| 4602-23 | Fault blocker system voltage | Return to port immediately - turn off unnecessary loads and check battery connections. Service engine before next use. | **yes** |
| 3061-16 | Fuel pump | Fuel pump is not working properly. Return to port immediately - service engine before next use. | **yes** |
| 842-16  | Wideband O2 sensor heater - starboard bank (S1) | Exhaust oxygen sensor is not working properly. | no |
| 822-16  | Wideband O2 sensor heater - port bank (S1) | Exhaust oxygen sensor is not working properly. | no |

Notes:
- `842-16` and `822-16` are the two exhaust O2 sensor banks on the **starboard
  engine** (starboard-side and port-side banks respectively) — both correctly
  tagged to the STBD engine; "port/starboard bank" describes sensor position,
  not the engine.
- Strings are stored as ASCII (`O2`, `-`) to avoid encoding surprises.
- `946-6`'s advisory is intentionally empty (its Line 3 is blank; we do not
  fall back to Line 2).

## Decisions (from brainstorming)

- Build **both**: rich offline text and critical seeds.
- Text model: **Title + advisory** (drop Line 2).
- Audible set: the 3 critical/emergency codes **plus** Drive Lube Low —
  `{1104-21, 1109-23, 3061-16, 4602-23}`.
- Rendering: **Title in the notification message, advisory in the `vvm` block**.
- Codes are **Universal `fault_key`s**, keyed directly.
- Data stays an **inline dict** in `fault_decoder.py` (8 hand-maintained
  entries; a JSON file would be over-engineering).

## Design

### 1. Fault text data (`vvm_to_signalk/fault_decoder.py`)

Replace the `{key: str}` map with a `{key: FaultText}` map, where `FaultText`
is a small `namedtuple("FaultText", ["title", "advisory"])` (advisory may be
`None`). Populate with the 8 rows above.

`Fault` accessors:
- `description` (existing property) now returns the **title** (`FAULT_TEXT[key].title`)
  or `None`. This preserves the existing message and `vvm.description` contract,
  now with real text.
- New `advisory` property returns `FAULT_TEXT[key].advisory` or `None`
  (also `None` when the code is unknown).

Unknown codes continue to fall back to the bare key (no text) — unchanged.

### 2. Notification rendering (`vvm_to_signalk/signalk_publisher.py`)

In `accept_fault`, the message is unchanged in shape
(`"Engine {pos} fault {key}: {title}"` — the title comes from `description`).
Add `"advisory": fault.advisory` to the `extra`/`vvm` dict alongside the
existing `faultId`, `failureTypeId`, `severity`, `type`, `description` fields.

### 3. Critical seeds (`vvm_to_signalk/notification_policy.py`)

Populate the previously-empty set:

```python
CRITICAL_FAULT_KEYS = {"1104-21", "1109-23", "3061-16", "4602-23"}
```

No policy-logic change: `state_for("fault", key, is_active)` already returns
`alarm` iff `key in CRITICAL_FAULT_KEYS`, so these four now render as
`alarm` + `["visual","sound"]` when active, and every other fault stays
`alert` + `["visual"]`.

### 4. Consistency guard (test)

Mirror the existing Guardian/bitfield label-drift guard: assert
`CRITICAL_FAULT_KEYS <= set(FAULT_TEXT)`. A critical code must have known text,
so a typo in either place fails loudly.

## Testing / success criteria

- `fault_decoder`: `Fault.description` returns the title and `Fault.advisory`
  returns the Line-3 text for each of the 8 known codes; both are `None` for an
  unknown code.
- `signalk_publisher.accept_fault`: for a known critical code (e.g. `1109-23`)
  the delta is `state="alarm"`, `method=["visual","sound"]`, message contains
  the title, and `vvm.advisory` carries the advisory. For a known non-critical
  code (e.g. `946-6`) the delta is `state="alert"`, `method=["visual"]`, and
  `vvm.advisory` is `None`.
- `notification_policy`: the four critical keys classify as `alarm`; a
  non-critical/unknown key classifies as `alert`. Rename the existing
  `test_faults_are_alert_empty_allowlist` (the allowlist is no longer empty) to
  use a genuinely non-critical key, and add a positive critical-key case.
- Consistency guard passes: `CRITICAL_FAULT_KEYS <= set(FAULT_TEXT)`.
- Update `test_accept_fault_message_includes_known_description` for the new
  `946-6` title.
- Full suite (`python3 -m pytest -q`) stays green.

## Out of scope

- Adding a debug log for faults with no text (codes are treated as known
  Universal keys; revisit if real `0x201` frames decode to unexpected keys).
- Deriving criticality from the free-text Category (explicit key set is the
  source of truth, consistent with the Guardian/bitfield allowlists).
- Moving fault text to a JSON data file (inline dict is sufficient at this size).
- Legacy-fault text (all sheet codes are Universal).
