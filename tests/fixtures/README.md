# Test fixtures

## capture_healthy.jsonl

Real channel-data BLE notifications extracted from the boat's BTSnoop captures
in `docs/bt-logs/*.log`. Each line is `{"handle": "0x00XX", "hex": "..."}` — the
raw ATT notification value bytes (2-byte little-endian item-id + per-engine
values).

**Healthy-only:** both source captures are normal running sessions and contain
**zero fault events** — no `0x201` fault frames and none of the offline-fault
items (Guardian Cause 87, MIL 106, Seven-Function Gauge 97). On this device the
active channel map does not include 87/97/106, so those notification paths are
dormant here; faults would instead arrive over `0x201`. The audible-alarm
policy is therefore validated synthetically in `tests/test_fault_policy_matrix.py`.

Payloads are deduped and capped at 20 distinct values per handle.

**Regenerate:** `python3 tools/extract_capture_fixture.py`
