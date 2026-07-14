# VVM Notification Policy: Quiet-by-Default with a Critical Allowlist

Date: 2026-07-13
Status: Approved (design)

## Problem

Every VVM notification the connector publishes is hardcoded to
`state="alarm"` with `method=["visual","sound"]` when active. SignalK clients
(KIP in particular) beep on any notification whose `method` includes `"sound"`,
so a trivial fault is as loud as an engine-protection shutdown. There is no
gradation and no way to silence low-value notifications short of muting the
client entirely.

We want the connector to be **quiet by default** and reserve the audible alarm
for a small, curated set of genuinely-critical engine-protection conditions.

## Key constraint: severity is opaque

Universal faults carry a raw 3-bit `severity` integer (0–7, `num & 0x7` in
`fault_decoder.py`). Its meaning is **not defined in this codebase** — the
official app resolves it via a cloud table we do not have. Legacy faults, and
the enum/bitfield offline paths (Guardian Cause, MIL, Seven-Function Gauge),
carry **no severity at all**.

**Decision:** we do **not** use the raw severity integer to drive notification
policy (no invented 0–7 scale). We still publish it in the `vvm` block for
reference. Policy keys off identifiers we actually understand.

## Design

### One decision, one derivation

The policy makes exactly one decision — the notification `state` — and the
`method` is derived mechanically from the state via a single lookup:

| state    | method               | KIP effect            |
|----------|----------------------|-----------------------|
| `alarm`  | `["visual","sound"]` | red banner + audible  |
| `alert`  | `["visual"]`         | amber banner, silent  |
| `normal` | `[]`                 | cleared               |

State rule:

- active **and** on the critical allowlist → `alarm`
- active **and** not on the allowlist → `alert`
- inactive / cleared → `normal`

### Critical allowlist (seeded)

New module `vvm_to_signalk/notification_policy.py` holds the allowlist and the
helpers. Seeded only with conditions we understand semantically:

- **Guardian Cause (item 87)** — overheat + oil set:
  `GC_CHI`, `GC_TEMPERATURE_HIGH`, `GC_BLK_PRESS_LOW`, `GC_LOW_OIL`,
  `GC_CRITICAL_OIL`, `GC_OIL_PRESSURE`.
  All other Guardian causes are active-but-`alert` (visual-only).
- **Seven-Function Gauge bitfield (item 97)**:
  `Oil Fault`, `Water Pressure Fault`, `Coolant Temperature Fault`.
  Other set bits are `alert`.
- **Universal / Legacy faults (`accept_fault`)**: allowlist is **empty**.
  Fault identity is opaque, so every active fault is `alert` (visual-only)
  until specific fault keys are curated in.
- **MIL — Malfunction Indicator Light (item 106)**: not seeded → `alert`
  (visual-only). It is an "inspect soon" indicator, not immediate protection.

Enum/flag label strings are taken verbatim from
`vvm_to_signalk/data/smartcraft_data_items.json` (verified 2026-07-13).

### Module API (`notification_policy.py`)

```python
METHOD_BY_STATE = {
    "alarm": ["visual", "sound"],
    "alert": ["visual"],
    "warn":  ["visual"],
    "normal": [],
}

# Critical allowlists, keyed by the identifier each publish path already has.
CRITICAL_GUARDIAN_CAUSES = {
    "GC_CHI", "GC_TEMPERATURE_HIGH", "GC_BLK_PRESS_LOW",
    "GC_LOW_OIL", "GC_CRITICAL_OIL", "GC_OIL_PRESSURE",
}
CRITICAL_BITFIELD_FLAGS = {
    "Oil Fault", "Water Pressure Fault", "Coolant Temperature Fault",
}
CRITICAL_FAULT_KEYS: set[str] = set()  # opaque; visual-only until curated

def is_critical(kind: str, key: str) -> bool:
    """kind is one of: 'guardian', 'bitfield', 'fault'. key is the enum text,
    flag name, or fault_key respectively."""

def state_for(kind: str, key: str, is_active: bool) -> str:
    """Return 'alarm' | 'alert' | 'normal' per the rule above."""
```

The enum path passes `kind="guardian"` for item 87 and `kind="mil"` for item
106. `is_critical` only recognizes the `guardian`, `bitfield`, and `fault`
allowlists; `"mil"` matches nothing, so an active MIL always resolves to
`alert`. Any unrecognized `kind` likewise resolves to `alert` when active
(fail-quiet, never fail-loud).

### Publisher changes (`signalk_publisher.py`)

1. `_send_notification`: derive `method` from `METHOD_BY_STATE[state]` instead
   of the inline `["visual","sound"] if state == "alarm" else []`. This adds the
   `alert → ["visual"]` case and keeps a single derivation point.
2. Enum path (87 / 106) at lines ~215–222: replace the hardcoded
   `"normal" if inactive else "alarm"` with `state_for(...)`.
3. Bitfield path (97) at lines ~223–229: replace the per-flag hardcoded
   `"alarm" if flag_val else "normal"` with `state_for("bitfield", flag_name, flag_val)`.
4. `accept_fault` at lines ~246–272: route through `_send_notification`
   (passing the `vvm` dict as `extra`) and use
   `state_for("fault", fault.fault_key, fault.is_active)`. This unifies the
   method derivation and, as a bonus, gives faults the same change-only dedup
   the other paths already have.

## Behavior change summary

- Nothing beeps except the seeded Guardian overheat/oil causes and the three
  engine-protection bitfield flags.
- Everything else that used to be `alarm + sound` becomes `alert + visual`
  (amber, silent) while active, and `normal` when cleared.
- `accept_fault` now dedups on state per path (previously re-sent every cycle).

## Testing

- `state_for` truth table across the three kinds: active-critical → `alarm`,
  active-noncritical → `alert`, inactive → `normal`.
- `METHOD_BY_STATE` yields the expected arrays.
- Publisher paths (with a fake websocket capturing sent deltas):
  - Guardian `GC_CHI` active → `alarm` + `["visual","sound"]`; a non-seed
    Guardian cause active → `alert` + `["visual"]`; `GC_NONE` → `normal`.
  - Bitfield `Coolant Temperature Fault` set → `alarm`; a non-seed bit set →
    `alert`; clear → `normal`.
  - MIL Constant On → `alert` + `["visual"]`; MIL Off → `normal`.
  - `accept_fault` active (empty allowlist) → `alert` + `["visual"]` with the
    `vvm` extra intact; cleared → `normal`.
- Preserve/extend existing tests in `tests/` following their current patterns.

## Out of scope (future)

- Making the allowlist configurable from the connector config file rather than
  code constants.
- Resolving true Universal-fault severity semantics (requires the cloud or an
  offline SmartCraft/J1939 table we do not currently have).
