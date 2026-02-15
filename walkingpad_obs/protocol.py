"""BLE/GATT protocol for KingSmith WalkingPad A1 Pro."""

import asyncio
import logging
import subprocess
from dataclasses import dataclass
from typing import Callable, Optional

from bleak import BleakClient, BleakScanner

logger = logging.getLogger(__name__)

# GATT UUIDs (verified via GATT discovery):
#   fe01 = [read, notify]  — read status responses here
#   fe02 = [write-without-response] — send commands here
SERVICE_UUID = "0000fe00-0000-1000-8000-00805f9b34fb"
READ_UUID = "0000fe01-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000fe02-0000-1000-8000-00805f9b34fb"

# Packet bytes
HEADER_BYTE = 0xA2
START_BYTE = 0xF7
END_BYTE = 0xFD

# Commands
CMD_STATUS = 0x00
CMD_SPEED = 0x01
CMD_MODE = 0x02
CMD_BELT = 0x04

BELT_START = 0x01
BELT_STOP = 0x02

STATE_NAMES = {0: "Standby", 1: "Running", 2: "Starting", 5: "Idle", 6: "Paused"}
MODE_NAMES = {0: "Standby", 1: "Manual", 2: "Auto"}


def _build_packet(cmd: int, params: Optional[list[int]] = None) -> bytes:
    """Build a command packet in ph4-walkingpad format: [A2][CMD][PARAM][CHECKSUM].

    No F7/FD framing — the device disconnects if framing bytes are sent.
    """
    body = [HEADER_BYTE, cmd]
    if params:
        body.extend(params)
    else:
        body.append(0x00)  # zero-pad when no params
    checksum = sum(body) & 0xFF
    body.append(checksum)
    return bytes(body)


def _parse_uint16_be(data, offset: int) -> int:
    return (data[offset] << 8) | data[offset + 1]


def _parse_uint24_be(data, offset: int) -> int:
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

    def __init__(self, mac: str, on_status: Optional[Callable] = None):
        self.mac = mac
        self.on_status = on_status
        self.stats = WalkingPadStats()
        self._client: Optional[BleakClient] = None
        self._ready = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    @property
    def connected(self) -> bool:
        return self._ready and self._client is not None and self._client.is_connected

    async def connect(self) -> None:
        """Connect to the WalkingPad via BLE with retry logic."""
        self._ready = False

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

                subprocess.run(
                    ["bluetoothctl", "trust", self.mac], capture_output=True, timeout=5
                )

                self._loop = asyncio.get_running_loop()
                self._client = BleakClient(device, disconnected_callback=self._on_disconnect)
                await self._client.connect(timeout=15.0)

                # Ensure GATT service discovery is complete (required on Python 3.14 / BlueZ)
                svcs = self._client.services
                if not svcs or not svcs.characteristics:
                    await asyncio.sleep(1)
                    svcs = self._client.services

                # Subscribe to notifications (bonus — may not fire on all devices)
                try:
                    await self._client.start_notify(READ_UUID, self._on_notify)
                except Exception:
                    pass  # Not critical — we poll via direct reads

                # Verify we can actually communicate with the device
                try:
                    await self._client.read_gatt_char(READ_UUID)
                except Exception:
                    await asyncio.sleep(0.5)
                    await self._client.read_gatt_char(READ_UUID)

                self._ready = True
                self.stats.connected = True
                logger.info("Connected to WalkingPad %s", self.mac)
                return
            except Exception as e:
                last_error = e
                logger.warning("Attempt %d failed: %s", attempt, e)
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
        self._ready = False
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(READ_UUID)
            except Exception:
                pass
            await self._client.disconnect()
        self.stats.connected = False

    def _on_disconnect(self, client: BleakClient) -> None:
        logger.warning("WalkingPad disconnected")
        self._ready = False
        self.stats.connected = False

    def _on_notify(self, sender, data: bytearray) -> None:
        """Handle BLE notification (bonus path)."""
        self._parse_response(bytes(data))

    def _parse_response(self, data: bytes) -> bool:
        """Parse a status response. Handles both framed (F7...FD) and raw data.

        Returns True if stats were updated.
        """
        if not data or len(data) < 4:
            return False

        # If framed (F7 ... FD), strip framing
        if data[0] == START_BYTE and data[-1] == END_BYTE:
            data = data[1:-1]  # strip F7 and FD

        # Now data should be: [A2] [CMD=A2] [state] [speed_hi] [speed_lo] [mode] ...
        # Or unframed: [A2] [A2] [state] ...
        # Need at least: A2 + A2 + 13 data bytes + checksum = 16 bytes
        if len(data) < 16:
            return False

        if data[0] != HEADER_BYTE:
            return False

        # data[1] is the response type — 0xA2 = current status
        if data[1] != 0xA2:
            return False

        self.stats.state = data[2]
        self.stats.speed_raw = _parse_uint16_be(data, 3)
        self.stats.mode = data[5]
        self.stats.time_seconds = _parse_uint24_be(data, 6)
        self.stats.distance_raw = _parse_uint24_be(data, 9)
        self.stats.steps = _parse_uint24_be(data, 12)
        self.stats.connected = True

        self._fire_callback()
        return True

    def _fire_callback(self):
        if self.on_status and self._loop:
            if asyncio.iscoroutinefunction(self.on_status):
                self._loop.create_task(self.on_status(self.stats))
            else:
                self.on_status(self.stats)

    async def _write(self, packet: bytes) -> None:
        if not self.connected:
            raise ConnectionError("Not connected to WalkingPad")
        await self._client.write_gatt_char(WRITE_UUID, packet, response=False)

    async def request_status(self) -> None:
        """Request status: write command to fe02, then read response from fe01."""
        await self._write(_build_packet(CMD_STATUS))
        await asyncio.sleep(0.15)
        # Read response directly from fe01 (notifications may not work)
        try:
            data = await self._client.read_gatt_char(READ_UUID)
            if data:
                self._parse_response(bytes(data))
        except Exception:
            pass

    async def start(self) -> None:
        logger.info("Starting belt")
        await self._write(_build_packet(CMD_MODE, [1]))
        await asyncio.sleep(0.3)
        await self._write(_build_packet(CMD_BELT, [BELT_START]))

    async def stop(self) -> None:
        logger.info("Stopping belt")
        await self._write(_build_packet(CMD_BELT, [BELT_STOP]))

    async def set_speed(self, kmh: float) -> None:
        speed_val = max(5, min(60, int(kmh * 10)))
        logger.info("Setting speed to %.1f km/h (raw=%d)", kmh, speed_val)
        await self._write(_build_packet(CMD_SPEED, [speed_val]))


async def scan_for_walkingpads(timeout: float = 10.0) -> list[dict]:
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
