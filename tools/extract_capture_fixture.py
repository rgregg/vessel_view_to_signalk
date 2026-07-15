"""One-time tool: extract real channel-data notification frames from the boat's
BTSnoop HCI captures into a compact committed fixture for replay tests.

Run from the repo root:

    python3 tools/extract_capture_fixture.py

Reads docs/bt-logs/*.log, keeps ATT Handle-Value Notifications whose 2-byte
little-endian item-id is present in the data dictionary (i.e. real channel
data; config/UserVar indications are excluded), dedups identical payloads, caps
20 distinct payloads per handle, and writes tests/fixtures/capture_healthy.jsonl.
Multi-fragment ACL packets (continuation flag set) are silently skipped; all
frames in the current captures fit in a single fragment.
"""

import glob
import json
import os
import struct

from vvm_to_signalk.data_dictionary import DataDictionary

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_GLOB = os.path.join(REPO_ROOT, "docs", "bt-logs", "*.log")
OUT_PATH = os.path.join(REPO_ROOT, "tests", "fixtures", "capture_healthy.jsonl")
MAX_PER_HANDLE = 20


def iter_btsnoop(path):
    """Yield raw H4 packet payloads from a BTSnoop file."""
    with open(path, "rb") as f:
        header = f.read(16)
        if header[:8] != b"btsnoop\x00":
            return
        while True:
            rec = f.read(24)
            if len(rec) < 24:
                return
            _olen, ilen, _flags, _drops, _ts = struct.unpack(">IIIIq", rec)
            data = f.read(ilen)
            if len(data) < ilen:
                return
            yield data


def parse_att_notification(data):
    """Return (att_handle, value_bytes) for an ATT Handle-Value Notification in
    a single-fragment ACL packet, else None."""
    if not data or data[0] != 0x02:  # H4 ACL only
        return None
    body = data[1:]
    if len(body) < 8:
        return None
    _acl_handle, _acl_len = struct.unpack("<HH", body[0:4])
    if len(body) < 4 + _acl_len:
        return None
    l2 = body[4:]
    l2len, cid = struct.unpack("<HH", l2[0:4])
    if cid != 0x0004:  # ATT channel
        return None
    att = l2[4:4 + l2len]
    if len(att) < 3 or att[0] != 0x1B:  # Handle-Value Notification opcode
        return None
    att_handle, = struct.unpack("<H", att[1:3])
    return att_handle, att[3:]


def main():
    dictionary = DataDictionary.load()
    by_handle = {}  # handle -> list of distinct hex payloads (insertion order)
    for path in sorted(glob.glob(LOG_GLOB)):
        for data in iter_btsnoop(path):
            parsed = parse_att_notification(data)
            if parsed is None:
                continue
            handle, value = parsed
            if len(value) < 2:
                continue
            item_id = int.from_bytes(value[:2], "little")
            if dictionary.by_id(item_id) is None:
                continue  # not real channel data (config/UserVar/etc.)
            seen = by_handle.setdefault(handle, [])
            hx = value.hex()
            if hx not in seen and len(seen) < MAX_PER_HANDLE:
                seen.append(hx)

    rows = []
    for handle, hexes in by_handle.items():
        for hx in hexes:
            rows.append({"handle": f"0x{handle:04x}", "hex": hx})
    rows.sort(key=lambda r: (r["handle"], r["hex"]))

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    ids = sorted({int.from_bytes(bytes.fromhex(r["hex"])[:2], "little") for r in rows})
    print(f"Wrote {len(rows)} frames across {len(by_handle)} handles to {OUT_PATH}")
    print(f"Distinct item-ids: {ids}")


if __name__ == "__main__":
    main()
