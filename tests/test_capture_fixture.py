"""Sanity checks on the committed capture fixture."""

import json
import os

from vvm_to_signalk.data_dictionary import DataDictionary

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "capture_healthy.jsonl")

# Complete set of channel item-ids observed in the boat captures.
EXPECTED_IDS = {1, 10, 150, 181, 182, 210, 212, 232, 251, 6000, 8000, 10000}


def _load_rows():
    with open(FIXTURE) as f:
        return [json.loads(line) for line in f if line.strip()]


def test_fixture_exists_and_nonempty():
    assert os.path.exists(FIXTURE), "run: python3 tools/extract_capture_fixture.py"
    assert len(_load_rows()) > 0


def test_fixture_rows_wellformed_and_known():
    d = DataDictionary.load()
    ids = set()
    for row in _load_rows():
        assert set(row) == {"handle", "hex"}
        raw = bytes.fromhex(row["hex"])
        assert len(raw) >= 2
        item_id = int.from_bytes(raw[:2], "little")
        assert d.by_id(item_id) is not None, f"unknown item-id {item_id}"
        ids.add(item_id)
    assert ids == EXPECTED_IDS
