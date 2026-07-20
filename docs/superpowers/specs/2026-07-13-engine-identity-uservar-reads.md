# Engine identity (UserVar Software/Calibration/Serial IDs) — design

**Date:** 2026-07-13
**Branch:** `engine-identity` (off `main`)
**Status:** Design, pending implementation plan

## Problem

The connector never reads the engine's SmartCraft identity. `_retrieve_device_info`
only reads the standard BLE Device Information strings for the VVM *dongle* (Model
Number, Device Name, Manufacturer, Firmware Revision), and on this hardware Model
Number and Firmware come back blank. No engine **Software ID** is captured anywhere
— confirmed absent from all boat logs.

That Software ID matters: it identifies the exact engine/ECM (so we can pick the
correct Mercury fault-code document — the fault-text tables are engine-family
specific) and it is the key Mercury's cloud uses to resolve fault text. The IDs live
in SmartCraft UserVar items (protocol-map.md §4), which the connector does not read.

## Goal

Read the engine identity items over BLE for active engines, log them, and publish
them to SignalK — without disrupting the connection or streaming.

Items (per protocol-map.md §7, `AccessType=UserVar`, one per engine, engine 1 = base):
- Software Id: 4000 (engine 1) … 4003 (engine 4)
- Calibration Id: 4004 … 4007
- Serial Number: 4008 … 4011
- ECU Serial Number: 4012 … 4015

For engine E (1-based) the item id is `base + (E-1)`.

## Design

### 1. Paged UserVar string reader (new)

UserVar string items are returned via a **paged** request/response on the UserVar
Command characteristic `0x111` (`DEVICE_NEXT_UUID`), per protocol-map.md §4:
- Request: write 3 bytes `[id_lo, id_hi, 0x00]` (item id uint16 LE + 0x00).
- Response page 0: `[0x00][id:2 LE][msgType][len:2 LE][data…]` — carries total `len`
  and the first data chunk.
- Continuation pages: `[page][data…]` (page = 1, 2, …), appended until `len` bytes
  are gathered. Then the assembled bytes are decoded as a string (drop trailing NULs).

The existing single-page reader `_request_configuration_data` cannot assemble multiple
pages, and a per-page-future approach races (a page can arrive before its future is
registered). Instead, add a **handler-fed accumulator**:

- State: `self._paged_read` — `None` normally; otherwise holds `{item_id, buffer,
  expected_len, future}`.
- `async _read_uservar_string(client, item_id, timeout) -> str | None`:
  1. Create a future; set `self._paged_read`.
  2. Write the 3-byte request to `DEVICE_NEXT_UUID`.
  3. `await asyncio.wait_for(future, timeout)`; decode bytes → string.
  4. `finally: self._paged_read = None`.
- In `notification_handler`, for `uuid == DEVICE_NEXT_UUID` **when a paged read is
  active**, feed the page into the accumulator instead of `_trigger_event_listener`:
  - page 0: parse `[00][id:2][msgType][len:2][data…]`; if the id doesn't match the
    requested item, treat as malformed (resolve `None`); else set `expected_len` and
    seed `buffer` with the page-0 data chunk.
  - page N≥1: append `data[1:]` to `buffer`.
  - when `len(buffer) >= expected_len`: resolve the future with `buffer[:expected_len]`.
  This is race-free: the handler sees every page in arrival order.

The existing single-page `0x111` reads in `_initalize_vvm` are untouched (they run
before the identity step; no `_paged_read` is active then).

### 2. `_retrieve_engine_identity(client)` step

Called from `_device_init_and_loop` right after `_initalize_vvm` (0x111 notify is
already enabled there) and before streaming is enabled — matching the native app,
which reads Software Id during connect, before streaming.

- Determine active engines from the item-10000 response already read in
  `_initalize_vvm` (`00102701010001` → engine 1 bitfield). Parse that bitfield into an
  active-engine set; default to `{1}` if unavailable.
- For each active engine E, read the four items (`4000/4004/4008/4012 + (E-1)`) via
  `_read_uservar_string`. For each non-None result: log at INFO
  (`Engine <E> Software Id: <value>`, etc.) and dispatch to receivers for publishing.

### 3. Output — SignalK + log + CSV

- Log each captured value at INFO.
- New receiver-interface method `accept_engine_identity(engine_id, kind, value)` where
  `kind ∈ {"softwareId","calibrationId","serialNumber","ecuSerialNumber"}`:
  - `SignalKPublisher`: publish a delta at
    `propulsion.<label>.vvm.<kind>` (label via `engine_label`), string value.
  - `CsvWriter`: no-op (identity is not time-series).
  - `ConfigDecoder`: no-op if it implements the receiver interface.

### 4. Error handling (deployed-connector safety)

Every read is **best-effort**. A timeout, malformed/short page, or id mismatch logs a
warning and yields `None` (that item skipped). The whole `_retrieve_engine_identity`
call is wrapped so any exception is caught and logged — it must **never** abort the
connect sequence or prevent streaming. Same principle as the `0x201` fault-subscribe
fallback.

## Testing

Unit:
- Paged assembler: single-page string; multi-page split reassembly; id-mismatch →
  None; trailing-NUL stripping; empty/short page → None.
- Per-engine item-offset math (`base + (E-1)` for each of the four bases).
- Active-engine parse from the item-10000 bitfield response.
- `SignalKPublisher.accept_engine_identity` emits the correct `propulsion.<label>.vvm.<kind>`
  path and string value; `CsvWriter.accept_engine_identity` is a no-op.

Integration:
- Fake BLE client that, on the identity request write, feeds paged responses into
  `notification_handler`; assert `_read_uservar_string` returns the assembled string.
- `_retrieve_engine_identity` reads the four items for the active engine set and
  dispatches to receivers; a failing/timeout read does not raise.

Hardware (post-merge, boat on):
- Confirm the connector logs real engine IDs (`Engine 1 Software Id: …`) and publishes
  `propulsion.port.vvm.softwareId` to SignalK, with streaming undisturbed.

## Out of scope (YAGNI)
- Reading identity for engines not reported active.
- Using the captured Software ID to drive any cloud/fault-text lookup (separate effort).
- Persisting identity beyond the log + live SignalK values.

## Risks
- New BLE traffic on a deployed connector. Mitigated: the app performs these exact
  reads during connect; reads are best-effort and cannot abort streaming; validated on
  hardware before trusting.
- Paged-read timing. Mitigated by the handler-fed accumulator (race-free) plus
  per-read timeout.
