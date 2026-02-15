"""BLE/GATT protocol for KingSmith WalkingPad A1 Pro."""

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

from bleak import BleakClient, BleakScanner

logger = logging.getLogger(__name__)

# GATT UUIDs — verified against ph4-walkingpad reference implementation:
#   fe01 = Notify (receive status packets)
#   fe02 = Write  (send commands)
SERVICE_UUID = "0000fe00-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fe01-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000fe02-0000-1000-8000-00805f9b34fb"

# Packet framing
START_BYTE = 0xF7
HEADER_BYTE = 0xA2
END_BYTE = 0xFD

# Commands
CMD_STATUS = 0x00
CMD_SPEED = 0x01
CMD_MODE = 0x02
CMD_BELT = 0x04

# Belt sub-commands
BELT_START = 0x01
BELT_STOP = 0x02

# States
STATE_NAMES = {
    0: "Standby",
    1: "Running",
    2: "Starting",
    5: "Idle",
    6: "Paused",
}

# Modes
MODE_NAMES = {
    0: "Standby",
    1: "Manual",
    2: "Auto",
}


def _build_packet(cmd: int, params: Optional[list[int]] = None) -> bytes:
    """Build a WalkingPad command packet with checksum."""
    body = [HEADER_BYTE, cmd]
    if params:
        body.extend(params)
    checksum = sum(body) & 0xFF
    return bytes([START_BYTE] + body + [checksum, END_BYTE])


def _parse_uint16_be(data: bytes, offset: int) -> int:
    return (data[offset] << 8) | data[offset + 1]


def _parse_uint24_be(data: bytes, offset: int) -> int:
    return (data[offset] << 16) | (data[offset + 1] << 8) | data[offset + 2]


@dataclass
class WalkingPadStats:
    """Current stats from the WalkingPad."""

    state: int = 0
    speed_raw: int = 0
    mode: int = 0
    time_seconds: int = 0
    distance_raw: int = 0
    steps: int = 0
    connected: bool = False

    @property
    def speed_kmh(self) -> float:
        return self.speed_raw / 10.0

    @property
    def distance_km(self) -> float:
        return self.distance_raw / 100.0

    @property
    def time_formatted(self) -> str:
        h, rem = divmod(self.time_seconds, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    @property
    def state_name(self) -> str:
        return STATE_NAMES.get(self.state, f"Unknown({self.state})")

    @property
    def mode_name(self) -> str:
        return MODE_NAMES.get(self.mode, f"Unknown({self.mode})")

    @property
    def is_running(self) -> bool:
        return self.state == 1

    @property
    def calories(self) -> int:
        cal = self.distance_km * 55.0
        if self.speed_kmh > 4.0:
            cal *= 1.10
        return int(cal)

    def to_dict(self) -> dict:
        return {
            "distance_km": round(self.distance_km, 2),
            "time_seconds": self.time_seconds,
            "time_formatted": self.time_formatted,
            "steps": self.steps,
            "speed_kmh": round(self.speed_kmh, 1),
            "state": self.state,
            "state_name": self.state_name,
            "mode": self.mode,
            "mode_name": self.mode_name,
            "calories": self.calories,
            "connected": self.connected,
            "is_running": self.is_running,
        }


class WalkingPadController:
    """BLE controller for the WalkingPad A1 Pro."""

    def __init__(self, mac: str, on_status: Optional[Callable[[WalkingPadStats], None]] = None):
        self.mac = mac
        self.on_status = on_status
        self.stats = WalkingPadStats()
        self._client: Optional[BleakClient] = None
        self._buffer = bytearray()
        self._ready = False  # True only after connect + start_notify

    @property
    def connected(self) -> bool:
        return self._ready and self._client is not None and self._client.is_connected

    async def connect(self) -> None:
        """Connect to the WalkingPad via BLE with retry logic.

        1. Removes stale BlueZ device cache
        2. Trusts the device (helps with random addresses)
        3. Scans fresh to discover the device
        4. Connects using BLEDevice object (auto-detects address type)
        5. Retries up to 3 times on failure
        """
        self._ready = False

        # Remove stale BlueZ device cache
        logger.debug("Clearing BlueZ cache for %s", self.mac)
        subprocess.run(["bluetoothctl", "remove", self.mac], capture_output=True, timeout=5)
        await asyncio.sleep(1)

        last_error = None
        for attempt in range(1, 4):
            try:
                logger.info("Scanning for WalkingPad %s (attempt %d/3)...", self.mac, attempt)
                device = await BleakScanner.find_device_by_address(self.mac, timeout=15.0)
                if device is None:
                    raise ConnectionError(
                        f"WalkingPad {self.mac} not found. Is it on and app disconnected?"
                    )
                logger.info("Found: %s (%s)", device.name, device.address)

                # Trust the device (helps BlueZ with random BLE addresses)
                subprocess.run(
                    ["bluetoothctl", "trust", self.mac], capture_output=True, timeout=5
                )

                self._client = BleakClient(device, disconnected_callback=self._on_disconnect)
                await self._client.connect(timeout=15.0)
                logger.info("BLE connected, subscribing to notifications...")
                await self._client.start_notify(NOTIFY_UUID, self._on_notify)
                self._ready = True
                self.stats.connected = True
                logger.info("Connected to WalkingPad %s", self.mac)
                return
            except Exception as e:
                last_error = e
                logger.warning("Attempt %d failed: %s", attempt, e)
                # Clean up partial connection
                if self._client:
                    try:
                        await self._client.disconnect()
                    except Exception:
                        pass
                    self._client = None
                if attempt < 3:
                    await asyncio.sleep(2)

        raise ConnectionError(f"Failed to connect after 3 attempts: {last_error}")

    async def disconnect(self) -> None:
        """Disconnect from the WalkingPad."""
        self._ready = False
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(NOTIFY_UUID)
            except Exception:
                pass
            await self._client.disconnect()
        self.stats.connected = False
        logger.info("Disconnected from WalkingPad")

    def _on_disconnect(self, client: BleakClient) -> None:
        logger.warning("WalkingPad disconnected")
        self._ready = False
        self.stats.connected = False

    def _on_notify(self, sender: int, data: bytearray) -> None:
        """Handle incoming BLE notification fragments."""
        self._buffer.extend(data)
        self._process_buffer()

    def _process_buffer(self) -> None:
        """Extract complete packets from the buffer."""
        while True:
            # Find start byte
            start_idx = -1
            for i, b in enumerate(self._buffer):
                if b == START_BYTE:
                    start_idx = i
                    break
            if start_idx < 0:
                self._buffer.clear()
                return

            # Discard bytes before start
            if start_idx > 0:
                self._buffer = self._buffer[start_idx:]

            # Find end byte
            end_idx = -1
            for i, b in enumerate(self._buffer):
                if b == END_BYTE and i > 0:
                    end_idx = i
                    break
            if end_idx < 0:
                return  # Incomplete packet, wait for more data

            # Extract packet
            packet = bytes(self._buffer[: end_idx + 1])
            self._buffer = self._buffer[end_idx + 1 :]
            self._parse_packet(packet)

    def _parse_packet(self, packet: bytes) -> None:
        """Parse a complete status packet."""
        if len(packet) < 18:
            logger.debug("Packet too short (%d bytes), ignoring", len(packet))
            return

        if packet[2] != 0xA2:
            # Not a status response
            return

        self.stats.state = packet[3]
        self.stats.speed_raw = _parse_uint16_be(packet, 4)
        self.stats.mode = packet[6]
        self.stats.time_seconds = _parse_uint24_be(packet, 7)
        self.stats.distance_raw = _parse_uint24_be(packet, 10)
        self.stats.steps = _parse_uint24_be(packet, 13)
        self.stats.connected = True

        logger.debug(
            "Status: %s speed=%.1f dist=%.2fkm steps=%d time=%s",
            self.stats.state_name,
            self.stats.speed_kmh,
            self.stats.distance_km,
            self.stats.steps,
            self.stats.time_formatted,
        )

        if self.on_status:
            self.on_status(self.stats)

    async def _write(self, packet: bytes) -> None:
        """Write a command packet to the WalkingPad."""
        if not self.connected:
            raise ConnectionError("Not connected to WalkingPad")
        await self._client.write_gatt_char(WRITE_UUID, packet, response=False)

    async def request_status(self) -> None:
        """Request current status from the WalkingPad."""
        await self._write(_build_packet(CMD_STATUS))

    async def start(self) -> None:
        """Start the belt."""
        logger.info("Starting belt")
        await self._write(_build_packet(CMD_MODE, [1]))  # Set manual mode first
        await asyncio.sleep(0.3)
        await self._write(_build_packet(CMD_BELT, [BELT_START]))

    async def stop(self) -> None:
        """Stop the belt."""
        logger.info("Stopping belt")
        await self._write(_build_packet(CMD_BELT, [BELT_STOP]))

    async def set_speed(self, kmh: float) -> None:
        """Set belt speed in km/h (0.5-6.0)."""
        speed_val = max(5, min(60, int(kmh * 10)))
        logger.info("Setting speed to %.1f km/h (raw=%d)", kmh, speed_val)
        await self._write(_build_packet(CMD_SPEED, [speed_val]))


async def scan_for_walkingpads(timeout: float = 10.0) -> list[dict]:
    """Scan for WalkingPad BLE devices."""
    logger.info("Scanning for WalkingPad devices (%ds)...", int(timeout))
    devices = await BleakScanner.discover(timeout=timeout)
    results = []
    for d in devices:
        name = d.name or ""
        if "KS-" in name.upper() or "WALKINGPAD" in name.upper():
            results.append({
                "name": name,
                "address": d.address,
                "rssi": d.rssi if hasattr(d, "rssi") else None,
            })
    return results
