"""bless GATT-server peripheral that emulates the VVM to the native app."""
import logging

from bless import BlessServer

logger = logging.getLogger(__name__)


class VvmProxyPeripheral:
    """Advertises a cloned VVM profile and relays app<->VVM via callbacks."""

    def __init__(self, name, mirrored, on_write, on_read, server_factory=BlessServer):
        self._name = name
        self._mirrored = mirrored
        self._on_write = on_write
        self._on_read = on_read
        self._server_factory = server_factory
        self._server = None
        self._char_to_service = {}

    async def start(self) -> None:
        """Build the cloned profile and begin advertising."""
        server = self._server_factory(name=self._name)
        server.read_request_func = self._handle_read
        server.write_request_func = self._handle_write
        for service in self._mirrored:
            await server.add_new_service(service.uuid)
            for char in service.characteristics:
                self._char_to_service[char.uuid] = service.uuid
                await server.add_new_characteristic(
                    service.uuid, char.uuid, char.properties,
                    bytearray(), char.permissions)
        await server.start()
        self._server = server
        logger.info("Proxy peripheral advertising as %s (%d chars)",
                    self._name, len(self._char_to_service))

    async def stop(self) -> None:
        """Stop advertising and disconnect the app."""
        if self._server is not None:
            await self._server.stop()
            self._server = None

    async def push_notification(self, uuid: str, data: bytes) -> None:
        """Deliver a VVM notification to a subscribed app."""
        if self._server is None:
            return
        service_uuid = self._char_to_service.get(uuid)
        if service_uuid is None:
            return
        char = self._server.get_characteristic(uuid)
        if char is None:
            return
        char.value = bytearray(data)
        self._server.update_value(service_uuid, uuid)

    def _handle_read(self, characteristic, **kwargs):
        """bless read callback: return the current value for the app."""
        try:
            return bytearray(self._on_read(characteristic.uuid))
        except Exception as e:
            logger.warning("proxy read error on %s: %s", characteristic.uuid, e)
            return bytearray()

    def _handle_write(self, characteristic, value, **kwargs):
        """bless write callback: forward the app's write to the VVM."""
        try:
            self._on_write(characteristic.uuid, bytes(value))
        except Exception as e:
            logger.warning("proxy write error on %s: %s", characteristic.uuid, e)
