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
CMD_START_BYTE = 0xF7   # commands from host → device
RESP_START_BYTE = 0xF8  # responses from device → host
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
    """Build a command packet: [F7][A2][CMD][PARAM...][CHECKSUM][FD]."""
    body = [HEADER_BYTE, cmd]
    if params:
        body.extend(params)
    else:
        body.append(0x00)  # zero-pad when no params
    checksum = sum(body) & 0xFF
    body.append(checksum)
    return bytes([CMD_START_BYTE] + body + [END_BYTE])


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
        self._loop = asyncio.get_running_loop()

        last_error = None
        for attempt in range(1, 4):
            try:
                # Attempt 1: try with existing BlueZ state (preserves pairing)
                # Attempt 2+: clear BlueZ cache and start fresh
                if attempt > 1:
                    subprocess.run(
                        ["bluetoothctl", "remove", self.mac],
                        capture_output=True, timeout=5,
                    )
                    await asyncio.sleep(1)

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

                self._client = BleakClient(device, disconnected_callback=self._on_disconnect)
                await self._client.connect(timeout=15.0)

                # Subscribe to notifications for receiving status responses
                try:
                    await self._client.start_notify(READ_UUID, self._on_notify)
                except Exception:
                    pass

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
        """Parse a status response from the WalkingPad.

        Response format (from device):
          [0] 0xF8       — response start byte
          [1] 0xA2       — response type (current status)
          [2] state      — belt state (0=standby, 1=running, 5=idle)
          [3] speed      — 1 byte, divide by 10 for km/h
          [4] mode       — 0=auto, 1=manual, 2=standby
          [5-7] time     — uint24 BE, seconds
          [8-10] dist    — uint24 BE, divide by 100 for km
          [11-13] steps  — uint24 BE
        """
        if not data or len(data) < 14:
            return False

        # Response starts with 0xF8 0xA2
        if data[0] == RESP_START_BYTE and data[1] == HEADER_BYTE:
            pass  # correct format
        # Also accept if read returns without F8 prefix (direct read path)
        elif data[0] == HEADER_BYTE and data[1] == HEADER_BYTE:
            pass  # A2 A2 format from direct read
        else:
            return False

        self.stats.state = data[2]
        self.stats.speed_raw = data[3]          # 1 byte, not 2!
        self.stats.mode = data[4]
        self.stats.time_seconds = _parse_uint24_be(data, 5)
        self.stats.distance_raw = _parse_uint24_be(data, 8)
        self.stats.steps = _parse_uint24_be(data, 11)
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
        """Request status: write framed command to fe02, then try read or notification."""
        await self._write(_build_packet(CMD_STATUS))
        await asyncio.sleep(0.2)
        # Try direct read — may work now that framed writes are accepted
        try:
            data = await self._client.read_gatt_char(READ_UUID)
            if data:
                self._parse_response(bytes(data))
                return
        except Exception:
            pass
        # Fallback: wait for notification callback
        await asyncio.sleep(0.3)

    async def start(self, speed_kmh: float = 2.0) -> None:
        logger.info("Starting belt")
        await self._write(_build_packet(CMD_MODE, [1]))
        await asyncio.sleep(0.3)
        await self._write(_build_packet(CMD_BELT, [BELT_START]))
        await asyncio.sleep(0.5)
        speed_val = max(5, min(60, int(speed_kmh * 10)))
        await self._write(_build_packet(CMD_SPEED, [speed_val]))

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
