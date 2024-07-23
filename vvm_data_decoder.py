import argparse
import asyncio
import logging

from bleak import BleakClient, BlackScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.uuids import normalize_uuid_16, uuid16_dict

logger = logging.getLogger(__name__)

uuid16_lookup = {v: normalize_uuid_16(k) for k, v in uuid16_dict.items()}

"""Standard UUIDs from BLE protocol"""
SYSTEM_ID_UUID = uuid16_lookup["System ID"]
MODEL_NBR_UUID = uuid16_lookup["Model Number String"]
DEVICE_NAME_UUID = uuid16_lookup["Device Name"]
FIRMWARE_REV_UUID = uuid16_lookup["Firmware Revision String"]
HARDWARE_REV_UUID = uuid16_lookup["Hardware Revision String"]
SOFTWARE_REV_UUID = uuid16_lookup["Software Revision String"]
MANUFACTURER_NAME_UUID = uuid16_lookup["Manufacturer Name String"]

"""Manufacturer specific UUIDs"""
DEVICE_STARTUP_UUID = "00000300-0000-1000-8000-ec55f9f5b963"
DEVICE_CONFIG_UUID = "00000001-0000-1000-8000-ec55f9f5b963"
DEVICE_NEXT_UUID = "00000111-0000-1000-8000-ec55f9f5b963"

"""Engine data parameters"""
ENGINE_RPM_UUID = "00000102-0000-1000-8000-ec55f9f5b963"
COOLANT_TEMPERATURE_UUID = "00000103-0000-1000-8000-ec55f9f5b963"
BATTERY_VOLTAGE_UUID = "00000104-0000-1000-8000-ec55f9f5b963"
UNK_105_UUID = "00000105-0000-1000-8000-ec55f9f5b963"
ENGINE_RUNTIME_UUID = "00000106-0000-1000-8000-ec55f9f5b963"
CURRENT_FUEL_FLOW_UUID = "00000107-0000-1000-8000-ec55f9f5b963"
UNK_108_UUID = "00000108-0000-1000-8000-ec55f9f5b963"
UNK_109_UUID = "00000109-0000-1000-8000-ec55f9f5b963"
OIL_PRESSURE_UUID = "0000010a-0000-1000-8000-ec55f9f5b963"
UNK_10B_UUID = "0000010b-0000-1000-8000-ec55f9f5b963"
UNK_10C_UUID = "0000010c-0000-1000-8000-ec55f9f5b963"
UNK_10D_UUID = "0000010d-0000-1000-8000-ec55f9f5b963"


def notification_handler(characteristic: BleakGATTCharacteristic, data: bytearray):
    """Simple notification handler which prints the data received"""
    logger.info("%s: %r", characteristic.description, data)

async def main(args: argparse.Namespace):
    logger.info("starting scan...")

    if args.address:
        device = await BleakScanner.find_device_by_address(
            args.address, cb=dict(use_bdaddr=args.macos_use_bdaddr)
        )
        if device is None:
            logger.error("could not find device with address '%s'", args.address)
            return
    else:
        device = await BleakScanner.find_device_by_name(
            args.name, cb=dict(use_bdaddr=args.macos_use_bdaddr)
        )
        if device is None:
            logger.error("could not find device with name '%s'", args.name)
            return

    logger.info("connecting to device...")

    async with BleakClient(device) as client:
        logger.info("Connected")

        await dump_device_data()

        await initalize_vvm()

        await client.start_notify(args.characteristic, notification_handler)
        await asyncio.sleep(5.0)
        await client.stop_notify(args.characteristic)

async def initalize_vvm(client: BleakClient):
    logger.debug("Initalizing VVM device...")


async def dump_device_data(client: BleakClient):
    system_id = await client.read_gatt_char(SYSTEM_ID_UUID)
    logger.info(
        "System ID: {0}".format(
            ":".join(["{:02x}".format(x) for x in system_id[::-1]])
        )
    )

    model_number = await client.read_gatt_char(MODEL_NBR_UUID)
    logger.info("Model Number: {0}".format("".join(map(chr, model_number))))
    
    try:
        device_name = await client.read_gatt_char(DEVICE_NAME_UUID)
        print("Device Name: {0}".format("".join(map(chr, device_name))))
    except Exception:
        pass

    manufacturer_name = await client.read_gatt_char(MANUFACTURER_NAME_UUID)
    logger.info("Manufacturer Name: {0}".format("".join(map(chr, manufacturer_name))))

    firmware_revision = await client.read_gatt_char(FIRMWARE_REV_UUID)
    logger.info("Firmware Revision: {0}".format("".join(map(chr, firmware_revision))))

    hardware_revision = await client.read_gatt_char(HARDWARE_REV_UUID)
    logger.info("Hardware Revision: {0}".format("".join(map(chr, hardware_revision))))

    software_revision = await client.read_gatt_char(SOFTWARE_REV_UUID)
    logger.info("Software Revision: {0}".format("".join(map(chr, software_revision))))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    device_group = parser.add_mutually_exclusive_group(required=True)

    device_group.add_argument(
        "--name",
        metavar="<name>",
        help="the name of the bluetooth device to connect to",
    )
    device_group.add_argument(
        "--address",
        metavar="<address>",
        help="the address of the bluetooth device to connect to",
    )

    parser.add_argument(
        "--macos-use-bdaddr",
        action="store_true",
        help="when true use Bluetooth address instead of UUID on macOS",
    )

    parser.add_argument(
        "characteristic",
        metavar="<notify uuid>",
        help="UUID of a characteristic that supports notifications",
    )

    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="sets the log level to debug",
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)-15s %(name)-8s %(levelname)s: %(message)s",
    )

    asyncio.run(main(args))