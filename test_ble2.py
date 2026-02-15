#!/usr/bin/env python3
"""BLE test v2: write status request to fe01, listen on fe01."""

import asyncio
import subprocess
import sys

from bleak import BleakClient, BleakScanner

MAC = sys.argv[1] if len(sys.argv) > 1 else "85:20:00:14:47:AF"

FE01 = "0000fe01-0000-1000-8000-00805f9b34fb"
FE02 = "0000fe02-0000-1000-8000-00805f9b34fb"

STATUS_CMD = bytes([0xF7, 0xA2, 0x00, 0xA2, 0xFD])

received = []


def on_notify(sender, data: bytearray):
    hex_str = data.hex(' ')
    received.append(data)
    print(f"  << NOTIFY: {hex_str}  ({len(data)} bytes)")
    if len(data) >= 18 and data[0] == 0xF7:
        state = data[3]
        speed = (data[4] << 8 | data[5]) / 10.0
        mode = data[6]
        time_s = (data[7] << 16 | data[8] << 8 | data[9])
        dist = (data[10] << 16 | data[11] << 8 | data[12]) / 100.0
        steps = (data[13] << 16 | data[14] << 8 | data[15])
        print(f"     Parsed: state={state} speed={speed} mode={mode} time={time_s}s dist={dist}km steps={steps}")


async def main():
    print(f"=== BLE Test v2: Write to fe01, Notify on fe01 ===\n")

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
    print("OK\n")

    print("Test A: Write status request to fe01...")
    await client.write_gatt_char(FE01, STATUS_CMD, response=False)
    await asyncio.sleep(2)

    if not received:
        print("\nNo notifications received from fe01 write. Trying fe02 write...")
        print("\nTest B: Write status request to fe02...")
        try:
            await client.write_gatt_char(FE02, STATUS_CMD, response=False)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"  fe02 write failed: {e}")

    if not received:
        print("\nNo data received at all. Waiting 10s for any spontaneous notifications...")
        await asyncio.sleep(10)

    print(f"\nTotal notifications received: {len(received)}")

    print("\nPolling 5x via fe01 write...")
    for i in range(5):
        try:
            await client.write_gatt_char(FE01, STATUS_CMD, response=False)
        except Exception as e:
            print(f"  Write error: {e}")
            break
        await asyncio.sleep(1)

    await client.disconnect()
    print("\nDone!")


asyncio.run(main())
