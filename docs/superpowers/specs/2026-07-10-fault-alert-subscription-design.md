# Fault Alert (0x201) subscription + safe fallback — design

**Date:** 2026-07-10
**Branch:** `fault-visibility` (off `main`)
**Status:** Design, pending implementation plan

## Problem

Real engine faults raised by the engines this season (e.g. "low gear lube",
"service engine light not connected") never reached SignalK or the logs. Both
are async SmartCraft fault codes delivered as BLE **indications** on the Fault
Alert characteristic `0x201`. The connector never subscribes to `0x201`, so the
fully-built fault decode path (`notification_handler` → `_handle_fault_notification`
→ `parse_fault` → `accept_fault`) never fires — `Fault received` has never
appeared in any retained log.

### Root cause

- `_setup_data_notifications` subscribes only where `"notify" in props`. `0x201`
  is **indicate-only**, so it is skipped.
- This is fallout from the #37 → #43 sequence: #37 tried to add fault support by
  subscribing to *all* indicate characteristics, which made the VVM reject the
  CCCD write on the control characteristics (`0x301/0x302/0x401/0x2a05`) with
  `ATT 0x0e` and drop the link (no engine data). #43 fixed the outage by
  reverting to **notify-only**, which also dropped the one indicate char we
  actually want — `0x201`. Fault support was collateral damage.

The offline-fault items (87 Guardian Cause / 97 Seven-Function-Gauge / 106 MIL)
that the connector polls are enum/bitfield summaries and do **not** carry these
specific codes, so they would not have caught these faults either.

## Native-app validation (done)

Parsed `docs/bt-logs/btsnoop_hci.log` (+ `.last.log`) — pure-stdlib btsnoop/HCI/
L2CAP/ATT parser — to extract the app's exact CCCD writes. Findings (identical
in both captures, repeated every connection cycle):

```
0x0016 ModuleCmd CCCD  = 0200   (indicate-enable)
0x0015 ModuleCmd       = 0d00   (stop stream)
0x0015 ModuleCmd       = 28000301 (request channel map)
0x005f Fault CCCD      = 0000   (DISABLE — clear stale sub)
0x005a UserVar CCCD    = 0200   (indicate) + item reads 10000/4042/4040
0x001e..0x004a chan CCCDs = 0100 (notify-enable, 0x102..0x10d)
0x0015 ModuleCmd       = 0d01   (STREAM START)
0x005f Fault CCCD      = 0200   (INDICATE-ENABLE)  <-- ~0.6s AFTER stream start
```

Conclusions:
1. The app subscribes to `0x201` with **indicate-enable (`0200`)** — confirms the fix.
2. It enables `0x201` **after** `0d01` stream-start (not before). Our implementation
   must match this ordering.
3. The app **never** writes CCCDs of `0x301/0x302/0x401/0x2a05` — confirms those
   caused the #37 drop and validates keeping them on the skip list.
4. The app writes `0000` (disable) before enabling. Redundant on our unbonded link
   (CCCD resets per connect); omitted unless live testing shows otherwise.
5. CCCD writes are acknowledged ATT Write Requests, so a device rejection surfaces
   as a synchronous exception — the fallback's failure detection is reliable.

## Design

### Scope

This branch bundles two commits:
1. **(committed)** Log un-parseable channel notifications, deduped per connection.
2. Fault Alert `0x201` subscription + safe fallback (this design).

Out of scope (YAGNI): logging offline-item values (87/97/106) on change. The two
observed faults come via `0x201`, which this covers.

### Subscription change

- `_setup_data_notifications` stays notify-only (still skips the dangerous control
  chars; existing regression test `test_setup_data_notifications_skips_indicate_only`
  preserved).
- Add a targeted subscription to Fault Alert `0x201` **after**
  `_set_streaming_mode(enabled=True)`, mirroring the app. `bleak.start_notify`
  auto-selects indications for an indicate-only characteristic.
- Gate it on an in-memory flag `_fault_subscribe_disabled` (default False).
- Human-readable fault text is cloud-dependent (protocol-map §3.5); we capture and
  publish code + engine position + active/cleared + severity/IDs only.

### Fallback state machine (in-memory, disable-after-1, retry-on-restart)

Instance flags:
- `_fault_subscribe_disabled: bool` — when True, skip `0x201`. Reset only by process
  restart (in-memory), so a restart re-tries `0x201` and picks up future firmware fixes.
- `_fault_subscribe_pending: bool` — True only in the window between attempting the
  `0x201` subscribe and confirming the connection survived it.

Flow (per connection, when not disabled):
1. After streaming is enabled, set `_fault_subscribe_pending = True`.
2. `await client.start_notify(0x201, handler)` inside try/except:
   - **raises** (e.g. `ATT 0x0e`) → log warning, `_fault_subscribe_disabled = True`,
     `_fault_subscribe_pending = False`. Do not propagate — streaming already runs.
   - **succeeds** → log `Subscribed to Fault Alert (0x201) indications` at INFO,
     `_fault_subscribe_pending = False` (the ACK means the CCCD write was accepted).
3. In `_device_init_and_loop`'s `finally`: if `_fault_subscribe_pending` is still True
   when the connection ends (a drop raced the ACK without a clean exception), set
   `_fault_subscribe_disabled = True` and log a warning. Always clear pending.

Attribution window is narrow — `[start_notify(0x201) → its ACK]` — so a healthy
session that disconnects hours later (pending already False) never disables faults.
On the next reconnect after a disable, `0x201` is skipped and engine data streams
normally.

### Observability

- INFO when subscribed; WARNING when a subscribe fails / is disabled.
- Faults themselves already log at INFO (`Fault received: %s`) and publish a SignalK
  `notifications.propulsion.<engine>.vvmFault.<key>` delta.

## Testing (TDD)

New tests in `tests/test_blelogic.py`:
- `0x201` **is** subscribed during connect when not disabled.
- Ordering: the `0x201` subscribe happens **after** the streaming-enable write.
- `start_notify(0x201)` raising → `_fault_subscribe_disabled` set, and skipped on the
  next connect.
- Drop while `_fault_subscribe_pending` (no clean exception) → disabled set.
- Successful subscribe clears `_fault_subscribe_pending`, so a later normal disconnect
  does **not** disable.
- When disabled, `0x201` is not subscribed.
- Preserve `test_setup_data_notifications_skips_indicate_only` (control chars skipped).

## Deployment / live validation

1. Merge to `main`, push a `vX.Y.Z` tag (the boat's `:1` image updates only on a
   semver tag — see boat deployment notes).
2. `docker compose pull vvm && up -d vvm` on the boat.
3. Watch several connect cycles: streaming stays up (no `ATT 0x0e` / no drop loop),
   `Subscribed to Fault Alert (0x201)` appears, and a subsequent fault produces a
   `Fault received` log + SignalK notification.
4. If the device rejects `0x201`, confirm the fallback disables it and streaming
   continues.

## Risks

- **Regression risk:** subscribing to an indicate char is what caused the #37 outage.
  Mitigated by matching the app exactly (subscribe only `0x201`, only after streaming),
  the acknowledged-write failure detection, and the disable-after-1 fallback.
- **False disable:** an unrelated BLE drop inside the narrow pending window could
  disable faults for the session; recovered automatically on restart (in-memory).
