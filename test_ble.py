#!/usr/bin/env python3
"""Quick BLE test: connect to WalkingPad and print raw notifications."""

import asyncio
import subprocess
import sys

from bleak import BleakClient, BleakScanner

MAC = sys.argv[1] if len(sys.argv) > 1 else "85:20:00:14:47:AF"

SERVICE = "0000fe00-0000-1000-8000-00805f9b34fb"
NOTIFY_FE01 = "0000fe01-0000-1000-8000-00805f9b34fb"
NOTIFY_FE02 = "0000fe02-0000-1000-8000-00805f9b34fb"
WRITE_FE01 = NOTIFY_FE01
WRITE_FE02 = NOTIFY_FE02

# Status request packet: F7 A2 00 A2 FD
STATUS_CMD = bytes([0xF7, 0xA2, 0x00, 0xA2, 0xFD])


def on_notify_fe01(sender, data: bytearray):
    print(f"  [fe01 NOTIFY] {data.hex(' ')}  ({len(data)} bytes)")


def on_notify_fe02(sender, data: bytearray):
    print(f"  [fe02 NOTIFY] {data.hex(' ')}  ({len(data)} bytes)")


async def main():
    print(f"=== WalkingPad BLE Test ===")
    print(f"MAC: {MAC}\n")

    # Clear BlueZ cache
    print("1. Clearing BlueZ cache...")
    subprocess.run(["bluetoothctl", "remove", MAC], capture_output=True, timeout=5)
    await asyncio.sleep(1)

    # Scan
    print("2. Scanning for device...")
    device = await BleakScanner.find_device_by_address(MAC, timeout=15.0)
    if not device:
        print("   FAILED: Device not found!")
        return
    print(f"   Found: {device.name} ({device.address})")

    # Trust
    subprocess.run(["bluetoothctl", "trust", MAC], capture_output=True, timeout=5)

    # Connect
    print("3. Connecting...")
    client = BleakClient(device)
    await client.connect(timeout=15.0)
    print(f"   Connected: {client.is_connected}")

    # List services and characteristics
    print("\n4. GATT Services:")
    for service in client.services:
        print(f"   Service: {service.uuid}")
        for char in service.characteristics:
            props = ", ".join(char.properties)
            print(f"     Char: {char.uuid}  [{props}]")

    # Subscribe to BOTH characteristics to see which one sends data
    print("\n5. Subscribing to notifications on BOTH fe01 and fe02...")
    try:
        await client.start_notify(NOTIFY_FE01, on_notify_fe01)
        print("   fe01: subscribed OK")
    except Exception as e:
        print(f"   fe01: FAILED - {e}")

    try:
        await client.start_notify(NOTIFY_FE02, on_notify_fe02)
        print("   fe02: subscribed OK")
    except Exception as e:
        print(f"   fe02: FAILED - {e}")

    # Send status requests and see what comes back
    print("\n6. Sending status requests (writing to fe01)...")
    try:
        await client.write_gatt_char(WRITE_FE01, STATUS_CMD, response=False)
        print("   Write to fe01: OK")
    except Exception as e:
        print(f"   Write to fe01: FAILED - {e}")

    await asyncio.sleep(1)

    print("\n7. Sending status request (writing to fe02)...")
    try:
        await client.write_gatt_char(WRITE_FE02, STATUS_CMD, response=False)
        print("   Write to fe02: OK")
    except Exception as e:
        print(f"   Write to fe02: FAILED - {e}")

    await asyncio.sleep(1)

    # Poll a few times
    print("\n8. Polling 5 times (1s interval)...")
    for i in range(5):
        print(f"   --- Poll {i+1} ---")
        try:
            await client.write_gatt_char(WRITE_FE02, STATUS_CMD, response=False)
        except Exception as e:
            print(f"   Write error: {e}")
        await asyncio.sleep(1)

    print("\n9. Disconnecting...")
    await client.disconnect()
    print("   Done!")


asyncio.run(main())
