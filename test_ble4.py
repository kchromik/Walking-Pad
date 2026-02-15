#!/usr/bin/env python3
"""BLE test v4: try all possible approaches."""

import asyncio
import subprocess
import sys

from bleak import BleakClient, BleakScanner

MAC = sys.argv[1] if len(sys.argv) > 1 else "85:20:00:14:47:AF"

FE01 = "0000fe01-0000-1000-8000-00805f9b34fb"
FE02 = "0000fe02-0000-1000-8000-00805f9b34fb"
MYSTERY = "00010203-0405-0607-0809-0a0b0c0d2b12"

# Different packet formats to try
PKT_UNFRAMED = bytes([0xA2, 0x00, 0x00, 0xA2])          # ph4 format
PKT_FRAMED = bytes([0xF7, 0xA2, 0x00, 0xA2, 0xFD])      # spec format
PKT_ALT = bytes([0xF7, 0xA2, 0x00, 0x00, 0xA2, 0xFD])   # with extra 00 param


def on_any(char_name):
    def handler(sender, data: bytearray):
        print(f"  << [{char_name}] {data.hex(' ')}  ({len(data)} bytes)")
        if len(data) >= 4:
            print(f"     First bytes: {' '.join(f'0x{b:02X}' for b in data[:6])}")
    return handler


async def main():
    print("=== BLE Test v4: Comprehensive ===\n")

    subprocess.run(["bluetoothctl", "remove", MAC], capture_output=True, timeout=5)
    await asyncio.sleep(1)

    device = await BleakScanner.find_device_by_address(MAC, timeout=15.0)
    if not device:
        print("Not found!")
        return
    print(f"Found: {device.name}")

    subprocess.run(["bluetoothctl", "trust", MAC], capture_output=True, timeout=5)

    client = BleakClient(device)
    await client.connect(timeout=15.0)
    print(f"Connected!\n")

    # Subscribe to all notifiable characteristics
    print("--- Subscribing to all notifiable chars ---")
    for svc in client.services:
        for char in svc.characteristics:
            if "notify" in char.properties:
                try:
                    await client.start_notify(char.uuid, on_any(char.uuid[-4:]))
                    print(f"  Subscribed: {char.uuid} [{', '.join(char.properties)}]")
                except Exception as e:
                    print(f"  Failed:     {char.uuid} - {e}")

    await asyncio.sleep(1)

    # Test 1: Direct read of fe01
    print("\n--- Test 1: Read fe01 directly ---")
    try:
        data = await client.read_gatt_char(FE01)
        print(f"  fe01 read: {data.hex(' ')}  ({len(data)} bytes)")
    except Exception as e:
        print(f"  fe01 read failed: {e}")

    # Test 2: Read mystery char
    print("\n--- Test 2: Read mystery char ---")
    try:
        data = await client.read_gatt_char(MYSTERY)
        print(f"  mystery read: {data.hex(' ')}  ({len(data)} bytes)")
    except Exception as e:
        print(f"  mystery read failed: {e}")

    # Test 3: Write unframed to fe02
    print(f"\n--- Test 3: Write unframed to fe02: {PKT_UNFRAMED.hex(' ')} ---")
    try:
        await client.write_gatt_char(FE02, PKT_UNFRAMED, response=False)
        print("  OK")
        await asyncio.sleep(2)
    except Exception as e:
        print(f"  Failed: {e}")

    # Re-check connection
    if not client.is_connected:
        print("  DISCONNECTED! Reconnecting...")
        await client.connect(timeout=15.0)

    # Test 4: Write framed to fe02
    print(f"\n--- Test 4: Write FRAMED to fe02: {PKT_FRAMED.hex(' ')} ---")
    try:
        await client.write_gatt_char(FE02, PKT_FRAMED, response=False)
        print("  OK")
        await asyncio.sleep(2)
    except Exception as e:
        print(f"  Failed: {e}")

    if not client.is_connected:
        print("  DISCONNECTED! Reconnecting...")
        await client.connect(timeout=15.0)

    # Test 5: Write to mystery char
    print(f"\n--- Test 5: Write unframed to mystery char ---")
    try:
        await client.write_gatt_char(MYSTERY, PKT_UNFRAMED, response=False)
        print("  OK")
        await asyncio.sleep(2)
    except Exception as e:
        print(f"  Failed: {e}")

    # Test 6: Just wait for spontaneous notifications
    print("\n--- Test 6: Waiting 10s for spontaneous data ---")
    await asyncio.sleep(10)

    # Test 7: Read fe01 again after all writes
    print("\n--- Test 7: Read fe01 again ---")
    try:
        data = await client.read_gatt_char(FE01)
        print(f"  fe01 read: {data.hex(' ')}  ({len(data)} bytes)")
        if len(data) >= 18 and data[0] == 0xF7:
            state = data[3]
            speed = (data[4] << 8 | data[5]) / 10.0
            steps = (data[13] << 16 | data[14] << 8 | data[15])
            print(f"  PARSED: state={state} speed={speed} steps={steps}")
    except Exception as e:
        print(f"  Failed: {e}")

    await client.disconnect()
    print("\nDone!")


asyncio.run(main())
