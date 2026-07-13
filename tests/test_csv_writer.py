"""Tests for the CSV Writer module"""

import asyncio
from vvm_to_signalk.csv_writer import CsvWriter, CsvWriterConfig


class FakeItem:
    """Minimal stand-in for DataItem used in CSV writer tests."""
    def __init__(self, name):
        self.name = name


class TestCsvWriterConfig:
    """Test the CsvWriterConfig class"""

    def test_default_config(self):
        config = CsvWriterConfig()
        assert not config.enabled
        assert config.filename == "./logs/data.csv"
        assert config.flush_interval == 1.0

    def test_read_dict(self):
        data = {
            "enabled": True,
            "filename": "/tmp/test_csv.csv",
            "interval": 5.0,
        }
        config = CsvWriterConfig(data)
        assert config.enabled
        assert config.filename == "/tmp/test_csv.csv"
        assert config.flush_interval == 5.0

    def test_valid_property(self):
        config = CsvWriterConfig()
        assert config.valid
        config.enabled = True
        config.filename = None
        assert not config.valid
        config.filename = "test.csv"
        assert config.valid
        config.flush_interval = 0
        assert not config.valid


def test_csv_writes_header_and_row(tmp_path):
    """CsvWriter creates a file with a header and data row after the flush timer fires."""
    path = tmp_path / "data.csv"
    cfg = CsvWriterConfig({"enabled": True, "filename": str(path), "interval": 0.01})
    writer = CsvWriter(cfg)

    async def run():
        await writer.accept_engine_data(FakeItem("RPM"), 1, 600.0)
        await asyncio.sleep(0.05)  # let the flush timer fire

    asyncio.run(run())
    text = path.read_text()
    assert "timestamp,1_RPM" in text
    assert "600.0" in text


def test_csv_disabled_writes_nothing(tmp_path):
    """CsvWriter does not create a file when disabled."""
    path = tmp_path / "data.csv"
    cfg = CsvWriterConfig({"enabled": False, "filename": str(path), "interval": 0.01})
    writer = CsvWriter(cfg)

    async def run():
        await writer.accept_engine_data(FakeItem("RPM"), 1, 600.0)
        await asyncio.sleep(0.03)

    asyncio.run(run())
    assert not path.exists()


def test_csv_update_active_items_noop():
    """update_active_items should not raise."""
    cfg = CsvWriterConfig()
    writer = CsvWriter(cfg)
    writer.update_active_items([1, 2, 3])  # should not raise


def test_accept_engine_identity_is_noop():
    """CSV writer ignores engine identity strings (not time-series)."""
    writer = CsvWriter(CsvWriterConfig({"enabled": False}))
    # Must not raise and must not write anything.
    asyncio.run(writer.accept_engine_identity(1, "softwareId", "X"))
