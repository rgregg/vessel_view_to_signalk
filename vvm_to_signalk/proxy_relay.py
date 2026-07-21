"""Coordinator wiring the VVM central to the app-facing peripheral."""
import asyncio
import concurrent.futures
import logging

from .gatt_mirror import mirror_profile
from .proxy_peripheral import VvmProxyPeripheral

logger = logging.getLogger(__name__)


class ProxyRelay:
    """Relays notifications VVM->app and writes/reads app->VVM."""

    def __init__(self, connection, proxy_config, advertised_name, loop,
                 peripheral_factory=VvmProxyPeripheral, capture=None):
        self._conn = connection
        self._config = proxy_config
        self._name = advertised_name
        self._loop = loop
        self._peripheral_factory = peripheral_factory
        self._capture = capture
        self._peripheral = None
        self._read_cache = {}
        self._pending = set()

    async def on_upstream_ready(self, services) -> None:
        """VVM link is up: clone the profile, advertise, start relaying."""
        for service in services:
            for ch in service.characteristics:
                if "read" in ch.properties:
                    try:
                        self._read_cache[ch.uuid] = await self._conn.proxy_read(ch.uuid)
                    except Exception as e:
                        logger.debug("proxy pre-read failed for %s: %s", ch.uuid, e)
        mirrored = mirror_profile(services)
        self._peripheral = self._peripheral_factory(
            self._name, mirrored,
            on_write=self._forward_write,
            on_read=self._serve_read)
        await self._peripheral.start()
        self._conn.set_notification_observer(self._forward_notification)
        logger.info("Proxy relay active (advertising %s)", self._name)

    async def on_upstream_lost(self) -> None:
        """VVM link dropped: stop advertising and clear the relay."""
        self._conn.set_notification_observer(None)
        if self._peripheral is not None:
            await self._peripheral.stop()
            self._peripheral = None
        self._read_cache.clear()
        logger.info("Proxy relay stopped (upstream lost)")

    def _forward_notification(self, uuid, data):
        """Observer body (called from the central's notification path)."""
        self._read_cache[uuid] = bytes(data)
        if self._capture is not None:
            self._capture.record("vvm->app", "notify", uuid, bytes(data))
        peripheral = self._peripheral
        if peripheral is not None:
            self._schedule(peripheral.push_notification(uuid, bytes(data)))

    def _forward_write(self, uuid, data):
        """Peripheral on_write body (called from bless callback thread/loop)."""
        if self._capture is not None:
            self._capture.record("app->vvm", "write", uuid, bytes(data))
        self._schedule(self._conn.proxy_write(uuid, bytes(data)))

    def _schedule(self, coro):
        """Schedule a coroutine on the relay's loop from on- or off-loop context,
        retaining the handle and logging any exception (fire-and-forget otherwise
        swallows failures — e.g. a failed app->VVM write)."""
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is self._loop:
            # Caller happened to fire on the relay's own loop (as it does in
            # tests, and in some bless backends); scheduling via create_task
            # avoids the two-iteration lag of run_coroutine_threadsafe when
            # there's no separate thread to bridge from.
            handle = self._loop.create_task(coro)
            self._pending.add(handle)
        else:
            # Real bless callbacks typically fire off-loop (a different
            # thread/executor); bridge back onto the relay's loop safely.
            handle = asyncio.run_coroutine_threadsafe(coro, self._loop)
        handle.add_done_callback(self._on_scheduled_done)

    def _on_scheduled_done(self, handle):
        self._pending.discard(handle)
        try:
            exc = handle.exception()
        except (asyncio.CancelledError, concurrent.futures.CancelledError):
            return
        if exc is not None:
            logger.warning("proxy scheduled op failed: %s", exc)

    def _serve_read(self, uuid) -> bytes:
        """Peripheral on_read body: last-known value for the char."""
        value = self._read_cache.get(uuid, b"")
        if self._capture is not None:
            self._capture.record("app->vvm", "read", uuid, value)
        return value
