"""Module for scanning devices"""

import asyncio
from bleak import BleakScanner

async def main():
        """Scan for BLE devies and print any discoveries"""
        
        devices = await BleakScanner.discover()
        for d in devices:
            print(d)

asyncio.run(main())