# Capture-Replay + Synthetic Fault-Matrix Test Harness

Date: 2026-07-14
Status: Approved (design)

## Problem

The quiet-by-default notification policy (see
`2026-07-13-vvm-notification-policy-design.md`) changed which VVM conditions
raise an audible alarm. Real fault events are rare on the boat, so we cannot
easily validate the alarm behavior live. We want a test harness that gives
durable confidence using the data we actually have.

## What the observed data actually contains

Both real BTSnoop captures in `docs/bt-logs/` (67k ATT notifications total)
were analyzed. **They are 100% healthy-running telemetry — zero fault events.**
Every notification is normal channel data for 12 items, all present in the
data dictionary:

| Item | Name | Item | Name |
|------|------|------|------|
| 1 | RPM | 10000 | Active Engines |
| 210 | Starboard Coolant Temp | 181 | Oil Pressure |
| 232 | Voltage | 212 | Block Pressure |
| 6000 | Fuel Burned Trip A | 182 | Oil Temperature |
| 150 | Engine Run Time | 251 | Seawater Temperature |
| 10 | Fuel Flow Total | 8000 | Fuel Remaining |

There are **no** `0x201` fault frames and **no** offline-fault items
(Guardian Cause 87, MIL 106, Seven-Function bitfield 97). The device's active
channel map does not even include 87/97/106, so those notification paths are
dormant on this boat — faults would instead arrive via `0x201`.

**Consequence:** validation splits into two suites with different data sources.
The *quiet/decode path* is validated against real captured bytes. The *alarm
policy path* has no observed data and is validated synthetically, driven by the
data dictionary (which is itself distilled from the observed/official protocol).

## Decisions (from brainstorming)

- Faults are **synthetic-only** — no real fault capture exists.
- Build **two clearly-separated suites**: real-capture replay + synthetic
  fault matrix.
- Extract a **compact committed fixture** from the btsnoop via a one-time
  tool; tests read the fixture, not the raw 4.9 MB binaries.
- The dormant offline-fault paths on this device are **documented in the
  fixture README**, with no test assertion.

## Part A — Real-capture replay (quiet-path golden)

### Extraction tool: `tools/extract_capture_fixture.py`

Run once (and to regenerate), not part of the test run. Mirrors the existing
`tools/generate_data_items.py` convention.

- Parses the BTSnoop HCI (H4) logs in `docs/bt-logs/`.
- Extracts ATT Handle-Value Notifications (opcode `0x1b`) on the channel-data
  handles (i.e. ATT payloads whose first 2 bytes are a little-endian item-id
  present in the data dictionary). Ignores config/UserVar indicate streams
  (`0x0015`/`0x0059`) — those are covered by existing decoder tests.
- Dedups identical payloads; caps at 20 distinct payloads per handle to keep
  the fixture small while preserving value variety.
- Writes `tests/fixtures/capture_healthy.jsonl` — one compact JSON object per
  line: `{"handle": "0x001d", "hex": "01005802000000000000"}`.
- Prints a summary (distinct item-ids, frame counts).

### Fixture: `tests/fixtures/capture_healthy.jsonl` + `README.md`

The README records provenance: source btsnoop file(s), that the capture is
**healthy-only (no faults)**, the note that this device's channel map lacks
items 87/97/106 (dormant offline-fault paths), and the one-line command to
regenerate via the extraction tool.

### Replay test: `tests/test_capture_replay.py`

Loads the fixture, builds a real `DataDictionary` and a `SignalKPublisher`
wired to a fake websocket (with `socket_connected = True`) that records every
delta sent. For each fixture frame the test calls
`decode_notification(bytes.fromhex(hex), dict)` to get `(item, values)`, then
calls `publisher.accept_engine_data(item, engine_id, value)` for each decoded
engine value. This is the faithful minimal path: `accept_engine_data` is
exactly where the offline-fault branch (items 87/97/106 → `_send_notification`)
lives, so the "no spurious alarms" assertion is meaningful, and it needs no
handle→UUID map or BLE client. It also exercises the SI-conversion path as a
bonus.

Assertions (all against real captured bytes):

1. **No spurious alarms:** across every replayed frame, no delta has a path
   starting `notifications.` and no delta's `method` contains `"sound"`. This
   is the core "healthy operation never beeps" guarantee.
2. **No unparsed channels:** every frame resolves to a known dictionary item;
   the set of decoded item-ids equals the 12 observed IDs. A newly-unparsed
   item fails the test loudly.
3. **Golden decode:** specific known values are produced — RPM raw `0x0258`
   → 600 rpm, Voltage raw `0x38bb` → 14.52 V (within tolerance after gain).

## Part B — Synthetic fault matrix (policy proof), dictionary-driven

`tests/test_fault_policy_matrix.py`. Driven by the **real data dictionary**
loaded via `DataDictionary.load()`, not hardcoded name lists, so it stays
honest as the dictionary evolves and catches allowlist/label drift.

1. **Guardian Cause (87):** iterate every enum entry in the dictionary. Assert
   the pipeline emits `state=alarm` (method `["visual","sound"]`) iff the label
   is in `CRITICAL_GUARDIAN_CAUSES`; `state=alert` (method `["visual"]`) for a
   non-zero non-critical label; `state=normal` (method `[]`) for value 0
   (`GC_NONE`).
2. **MIL (106):** off (0) → normal; on (1) → alert; never alarm.
3. **Seven-Function bitfield (97):** each defined bit set alone → `alarm` if
   the flag name is in `CRITICAL_BITFIELD_FLAGS` else `alert`; a clear bit →
   `normal`. Include one multi-bit combo asserting per-flag independence.
4. **Legacy faults (4-byte):** built via `parse_fault`; active → `alert`
   (empty `CRITICAL_FAULT_KEYS`), cleared → `normal`.
5. **Universal faults (9-byte):** built via `parse_fault` with `severity`
   varied across 0–7. Assert severity decodes correctly AND that state stays
   `alert` regardless of severity — locking the invariant that the opaque
   severity integer never drives policy.
6. **Label-drift guard (highest value):** assert every string in
   `CRITICAL_GUARDIAN_CAUSES` appears among item 87's enum values, and every
   string in `CRITICAL_BITFIELD_FLAGS` appears among item 97's bit names. If a
   label is renamed in the JSON, the allowlist would silently stop matching;
   this catches it.

## Files

- Create: `tools/extract_capture_fixture.py`
- Create: `tests/fixtures/capture_healthy.jsonl`
- Create: `tests/fixtures/README.md`
- Create: `tests/test_capture_replay.py`
- Create: `tests/test_fault_policy_matrix.py`
- No production code changes — purely test and tooling.

## Testing / success criteria

- `python3 -m pytest -q` stays green with the new suites included.
- The replay suite fails if healthy data ever produces a notification/alarm,
  if a channel becomes unparsed, or if a golden decode drifts.
- The fault matrix fails if the policy misclassifies any dictionary-defined
  Guardian cause, MIL state, or bitfield flag; if severity ever changes fault
  state; or if an allowlist label drifts out of the dictionary.

## Out of scope

- Harvesting real fault frames (none exist; revisit if a fault is ever
  captured — the fixture format and replay harness would extend to carry
  `0x201` frames routed to the fault path).
- Any production code change to `notification_policy.py` or the publisher.
- Asserting the dormant-path device shape (documented only, per decision).
