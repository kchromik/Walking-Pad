#!/usr/bin/env python3
"""BLE test v3: correct packet format (no F7/FD framing) + write to fe02."""

import asyncio
import subprocess
import sys

from bleak import BleakClient, BleakScanner

MAC = sys.argv[1] if len(sys.argv) > 1 else "85:20:00:14:47:AF"

FE01 = "0000fe01-0000-1000-8000-00805f9b34fb"  # notify
FE02 = "0000fe02-0000-1000-8000-00805f9b34fb"  # write

# ph4-walkingpad format: [A2] [CMD] [PARAM] [CHECKSUM]
# NO F7/FD framing!
STATUS_CMD = bytes([0xA2, 0x00, 0x00, 0xA2])  # status request


def on_notify(sender, data: bytearray):
    hex_str = data.hex(' ')
    print(f"  << NOTIFY: {hex_str}  ({len(data)} bytes)")
    if len(data) >= 18 and data[0] == 0xF7:
        state = data[3]
        speed = (data[4] << 8 | data[5]) / 10.0
        mode = data[6]
        time_s = (data[7] << 16 | data[8] << 8 | data[9])
        dist = (data[10] << 16 | data[11] << 8 | data[12]) / 100.0
        steps = (data[13] << 16 | data[14] << 8 | data[15])
        print(f"     STATE={state} SPEED={speed} MODE={mode} TIME={time_s}s DIST={dist}km STEPS={steps}")


async def main():
    print(f"=== BLE Test v3: Correct packet format ===\n")

    subprocess.run(["bluetoothctl", "remove", MAC], capture_output=True, timeout=5)
    await asyncio.sleep(1)

    print("Scanning...")
    device = await BleakScanner.find_device_by_address(MAC, timeout=15.0)
    if not device:
        print("Device not found!")
        return
    print(f"Found: {device.name}")

    subprocess.run(["bluetoothctl", "trust", MAC], capture_output=True, timeout=5)

    print("Connecting...")
    client = BleakClient(device)
    await client.connect(timeout=15.0)
    print(f"Connected: {client.is_connected}\n")

    print("Subscribing to fe01 notifications...")
    await client.start_notify(FE01, on_notify)

    print(f"Writing status request to fe02: {STATUS_CMD.hex(' ')}")
    await client.write_gatt_char(FE02, STATUS_CMD, response=False)
    print("Write OK! Waiting for response...\n")

    await asyncio.sleep(2)

    print("Polling 5x...")
    for i in range(5):
        print(f"  --- Poll {i+1} ---")
        await client.write_gatt_char(FE02, STATUS_CMD, response=False)
        await asyncio.sleep(1)

    await client.disconnect()
    print("\nDone!")


asyncio.run(main())
