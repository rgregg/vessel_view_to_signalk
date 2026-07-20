# Durable Logging for Unknown Fault Codes

Date: 2026-07-19
Status: Approved (design)

## Problem

Faults are logged today at `INFO` (`ble_connection._handle_fault_notification`
→ `logger.info("Fault received: %s", fault)`), which includes the `fault_key`.
That is durable (the boat runs at `INFO`, logs rotate across ~10 files), but a
*new* code — one we have no text for — logs identically to a known one, at
`INFO`, with no raw frame. So a novel fault seen during operation is easy to
miss, would vanish if the level were raised to `WARNING`, and lacks the raw
bytes for deep diagnosis. We want new codes to stand out and be reliably
capturable so they can be added to the fault-text map / observed-codes sheet.

## Design

In `ble_connection._handle_fault_notification(data)` (which holds both the raw
frame `data` and the decoded `fault`), after the existing per-event
`INFO "Fault received"` line, emit a `WARNING` when the fault's code has no
text — i.e. `fault.description is None` (the `fault_key` isn't in `FAULT_TEXT`).

The warning captures everything needed to record and diagnose the code:
`fault_key`, `fault_type`, engine, active/cleared, `failure_type_id`,
`severity`, `action_id`, and the raw frame hex.

**Dedup:** once per `fault_key` per connection, via a new
`self._unknown_fault_seen` set — mirroring the existing `_unparsed_seen`
pattern for unparsed channel data. Cleared alongside `_unparsed_seen` in
`_reset_unparsed_tracking` so a fresh connection re-surfaces still-unknown
codes. This prevents a re-firing fault from flooding the log.

**Unchanged:** the per-event `INFO "Fault received"` line (full history) and the
malformed-length `WARNING` in `fault_decoder` both stay. This only *adds* an
elevated, deduped flag for codes not in `FAULT_TEXT`.

New helper:

```python
def _log_unknown_fault(self, fault, data: bytes):
    if fault.fault_key in self._unknown_fault_seen:
        return
    self._unknown_fault_seen.add(fault.fault_key)
    logger.warning(
        "Unknown fault code %s (no text) type=%s engine=%s active=%s "
        "failureTypeId=%s severity=%s actionId=%s raw=%s",
        fault.fault_key, fault.fault_type, fault.engine_position,
        fault.is_active, fault.failure_type_id, fault.severity,
        fault.action_id, data.hex())
```

## Testing

Mirror the existing `test_unparsed_channel_data_*` tests, routing a fault frame
through `notification_handler` with the `0x201` UUID:
- An unknown Universal code (e.g. `1234-5`) → one `WARNING` containing
  `"Unknown fault code 1234-5"` and the raw frame hex.
- A known code (`946-6`, which has text) → no `"Unknown fault code"` warning.
- The same unknown code twice → logged only once (dedup).

## Out of scope

- A separate persistent fault ledger/file (the rotated `vvm_monitor.log` at
  `INFO` + this `WARNING` flag are sufficient).
- Legacy faults are all currently text-less, so they will each flag once — this
  is intended (they are exactly the unmapped codes).
