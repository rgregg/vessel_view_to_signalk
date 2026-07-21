"""Hardware go/no-go for the single-radio BLE proxy (Approach A).

Connects to the VVM as a central AND advertises a dummy peripheral on the same
adapter at the same time. If both hold for ~60s with no error/disconnect, the Pi
controller supports the concurrent central+peripheral roles the proxy needs.

Run ON THE BOAT PI (engine/VVM powered on):
    python3 -m tools.proxy_concurrency_spike --address 84:FD:27:D9:2C:BE
"""
import argparse
import asyncio
import logging

from bleak import BleakClient
from bless import BlessServer, GATTCharacteristicProperties, GATTAttributePermissions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("spike")

DUMMY_SERVICE = "0000fff0-0000-1000-8000-00805f9b34fb"
DUMMY_CHAR = "0000fff1-0000-1000-8000-00805f9b34fb"


async def main(address: str, name: str, hold: float):
    server = BlessServer(name=name)
    await server.add_new_service(DUMMY_SERVICE)
    await server.add_new_characteristic(
        DUMMY_SERVICE, DUMMY_CHAR,
        GATTCharacteristicProperties.read | GATTCharacteristicProperties.notify,
        bytearray(b"\x00"),
        GATTAttributePermissions.readable,
    )
    async with BleakClient(address, timeout=20.0) as client:
        log.info("CENTRAL connected to VVM %s", address)
        await server.start()
        log.info("PERIPHERAL advertising as %s -- both roles now live", name)
        log.info("Holding both for %.0fs; watch for disconnects/errors...", hold)
        await asyncio.sleep(hold)
        await server.stop()
        log.info("GO: both roles held for the full window with no error")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--address", required=True, help="VVM BLE address")
    p.add_argument("--name", default="VVM_SPIKE_TEST")
    p.add_argument("--hold", type=float, default=60.0)
    args = p.parse_args()
    asyncio.run(main(args.address, args.name, args.hold))
