from datetime import datetime, timezone
from vvm_to_signalk.traffic_capture import TrafficCapture


def test_record_writes_one_line(tmp_path):
    path = tmp_path / "capture.log"
    cap = TrafficCapture(str(path))
    ts = datetime(2026, 7, 20, 1, 2, 3, tzinfo=timezone.utc)
    cap.record("app->vvm", "write", "00000001-0000-1000-8000-ec55f9f5b963",
               bytes.fromhex("a1b2"), now=ts)
    cap.close()
    line = path.read_text().strip()
    assert line == ("2026-07-20T01:02:03+00:00 app->vvm write "
                    "00000001-0000-1000-8000-ec55f9f5b963 a1b2")


def test_disabled_capture_writes_nothing(tmp_path):
    path = tmp_path / "capture.log"
    cap = TrafficCapture(str(path), enabled=False)
    cap.record("vvm->app", "notify", "x", b"\x01", now=datetime.now(timezone.utc))
    cap.close()
    assert not path.exists()


def test_empty_data_has_empty_hex(tmp_path):
    path = tmp_path / "capture.log"
    cap = TrafficCapture(str(path))
    ts = datetime(2026, 7, 20, 0, 0, 0, tzinfo=timezone.utc)
    cap.record("app->vvm", "subscribe", "uuid", b"", now=ts)
    cap.close()
    line = path.read_text().rstrip("\n")
    assert line.endswith("subscribe uuid ")
