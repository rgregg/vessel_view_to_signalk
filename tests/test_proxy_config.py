from vvm_to_signalk.proxy_config import ProxyConfig


def test_default_disabled_and_invalid():
    c = ProxyConfig()
    assert c.enabled is False
    assert c.valid is False
    assert c.capture_file == "./logs/ble_capture.log"
    assert c.advertised_name is None


def test_read_enables_and_overrides():
    c = ProxyConfig({"enabled": True, "capture-file": "/x/cap.log",
                     "advertised-name": "VVM_TEST"})
    assert c.enabled is True
    assert c.valid is True
    assert c.capture_file == "/x/cap.log"
    assert c.advertised_name == "VVM_TEST"


def test_read_none_is_noop():
    c = ProxyConfig()
    c.read(None)
    assert c.enabled is False
