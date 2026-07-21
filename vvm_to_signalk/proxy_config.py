"""Configuration for the BLE GATT proxy mode."""


class ProxyConfig:
    """Parses the optional `proxy` config section. Disabled by default."""

    def __init__(self, data: dict | None = None):
        self._enabled = False
        self._capture_file = "./logs/ble_capture.log"
        self._advertised_name = None
        if data is not None:
            self.read(data)

    def read(self, data: dict | None) -> None:
        """Read proxy settings from a dict; None is a no-op."""
        if data is None:
            return
        self._enabled = bool(data.get("enabled", self._enabled))
        self._capture_file = data.get("capture-file", self._capture_file)
        self._advertised_name = data.get("advertised-name", self._advertised_name)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def capture_file(self) -> str:
        return self._capture_file

    @property
    def advertised_name(self):
        return self._advertised_name

    @property
    def valid(self) -> bool:
        """The proxy is only 'valid' (should be constructed) when enabled."""
        return self._enabled
