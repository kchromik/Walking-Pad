"""BLE scanner for WalkingPad devices."""

import asyncio
import sys

from .protocol import scan_for_walkingpads


async def main() -> None:
    print("Scanning for WalkingPad devices (10 seconds)...\n")
    devices = await scan_for_walkingpads(timeout=10.0)

    if not devices:
        print("No WalkingPad devices found.")
        print()
        print("Troubleshooting:")
        print("  - Is the WalkingPad powered on?")
        print("  - Is the smartphone app disconnected? (Only one BLE connection at a time)")
        print("  - Are you close enough to the device?")
        sys.exit(1)

    print(f"Found {len(devices)} device(s):\n")
    for d in devices:
        rssi_str = f"  RSSI: {d['rssi']} dBm" if d["rssi"] is not None else ""
        print(f"  {d['name']}  {d['address']}{rssi_str}")

    print()
    print("Use the MAC address with:  python -m walkingpad_obs --mac <ADDRESS>")


if __name__ == "__main__":
    asyncio.run(main())
