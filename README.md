# WalkingPad OBS Overlay

A desktop app and local web service that connects via Bluetooth Low Energy (BLE) to a KingSmith WalkingPad treadmill, reads live stats (steps, distance, time, speed), and provides:

- **Desktop GUI** — Tkinter-based control panel with device scanning, belt controls, and live stats
- **OBS Browser Source overlay** — Glassmorphism-styled overlay for livestreaming
- **Web Dashboard** — Browser-based control panel with the same functionality

Tested with the **KingSmith WalkingPad A1 Pro**.

## Installation

```bash
git clone git@github.com:kchromik/Walking-Pad.git
cd Walking-Pad
./install.sh
```

The install script creates a Python venv, installs dependencies, and adds a desktop entry to your start menu.

### Prerequisites

- Python 3.12+
- Bluetooth adapter with BLE support
- Linux with BlueZ (tested on Arch / CachyOS)
- `tk` package for the GUI (`paru -S tk` on Arch)
- WalkingPad must be powered on and **not** connected to the smartphone app (only one BLE connection at a time)

## Usage

### Desktop App (recommended)

Launch from your start menu ("WalkingPad Control") or run:

```bash
./start.sh
```

1. Click **Scannen** to find your WalkingPad
2. Select the device and click **Verbinden**
3. Use the **Start/Stop** buttons and speed slider to control the belt
4. Click **Dashboard öffnen** or **OBS Overlay öffnen** to open the web UIs

### Headless / CLI Mode

```bash
./start.sh --mac "85:20:00:14:47:AF"
```

This starts the web server without the GUI. Useful for running on a headless machine.

#### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--mac MAC` | — | WalkingPad BLE MAC address (required for headless mode) |
| `--host HOST` | `0.0.0.0` | Server bind address |
| `--port PORT` | `8777` | Server port |
| `--poll-interval S` | `1.0` | Status polling interval in seconds |
| `--verbose` | off | Enable debug logging |

### Finding Your MAC Address

```bash
./start.sh  # Use the GUI scan button
# or
.venv/bin/python -m walkingpad_obs.scan
```

## OBS Setup

1. Add a **Browser Source** in OBS
2. Set URL to `http://127.0.0.1:8777/overlay`
3. Set width to **800** and height to **200**
4. Check "Shutdown source when not visible" (optional)

## API Endpoints

| URL | Method | Description |
|-----|--------|-------------|
| `/` | GET | Web Dashboard |
| `/overlay` | GET | OBS Browser Source overlay |
| `/ws` | WebSocket | Live stats stream (JSON) |
| `/api/stats` | GET | Current stats as JSON |
| `/api/start` | POST | Start the belt |
| `/api/stop` | POST | Stop the belt |
| `/api/speed/{kmh}` | POST | Set speed (0.5–6.0 km/h) |

## BLE Protocol

Communication uses the GATT service `0xFE00` with two characteristics:

| UUID | Properties | Role |
|------|-----------|------|
| `0xFE01` | Read, Notify | Receive status responses |
| `0xFE02` | Write Without Response | Send commands |

Commands are sent as `[F7][A2][CMD][PARAM][CHECKSUM][FD]`. Responses arrive as notifications starting with `[F8][A2]` followed by state, speed, mode, time, distance, and step count.

Based on the protocol work from [QWalkingPad](https://github.com/DorianRudolph/QWalkingPad) and [ph4-walkingpad](https://github.com/ph4r05/ph4-walkingpad).

## License

MIT
