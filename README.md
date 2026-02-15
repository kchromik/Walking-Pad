# WalkingPad OBS Overlay

Local web service that connects via Bluetooth Low Energy (BLE) to a **KingSmith WalkingPad A1 Pro**, reads live data (steps, distance, time, speed), and displays it as an **OBS Browser Source overlay**. Includes a web dashboard for controlling the treadmill.

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Find your WalkingPad's MAC address
python -m walkingpad_obs.scan

# Start the server
python -m walkingpad_obs --mac "AA:BB:CC:DD:EE:FF"
```

### CLI Options

```
--mac MAC          WalkingPad BLE MAC address (required)
--host HOST        Server host (default: 0.0.0.0)
--port PORT        Server port (default: 8777)
--poll-interval S  Status polling interval in seconds (default: 1.0)
--verbose          Enable debug logging
```

## OBS Setup

1. Add a **Browser Source** in OBS
2. Set URL to `http://127.0.0.1:8777/overlay`
3. Set width to **800** and height to **200**
4. Check "Shutdown source when not visible" (optional)

## Endpoints

| URL | Method | Description |
|-----|--------|-------------|
| `http://127.0.0.1:8777/` | GET | Web Dashboard (control + stats) |
| `http://127.0.0.1:8777/overlay` | GET | OBS Browser Source overlay |
| `http://127.0.0.1:8777/ws` | WS | WebSocket live stats stream |
| `http://127.0.0.1:8777/api/stats` | GET | Current stats as JSON |
| `http://127.0.0.1:8777/api/start` | POST | Start the belt |
| `http://127.0.0.1:8777/api/stop` | POST | Stop the belt |
| `http://127.0.0.1:8777/api/speed/{kmh}` | POST | Set speed (0.5–6.0 km/h) |

## Requirements

- Python 3.12+
- Bluetooth adapter with BLE support
- WalkingPad must be powered on and **not** connected to the smartphone app (only one BLE connection at a time)
- CachyOS / Arch Linux (or any Linux with BlueZ)
