"""FastAPI server for WalkingPad OBS Overlay."""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from .protocol import WalkingPadController, WalkingPadStats

logger = logging.getLogger(__name__)

app = FastAPI(title="WalkingPad OBS Overlay")

# Global state
controller: Optional[WalkingPadController] = None
ws_clients: set[WebSocket] = set()
_poll_interval: float = 1.0

STATIC_DIR = Path(__file__).parent


# --- HTML routes ---


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return (STATIC_DIR / "dashboard.html").read_text(encoding="utf-8")


@app.get("/overlay", response_class=HTMLResponse)
async def overlay():
    return (STATIC_DIR / "overlay.html").read_text(encoding="utf-8")


# --- REST API ---


@app.get("/api/stats")
async def api_stats():
    if controller:
        return JSONResponse(controller.stats.to_dict())
    return JSONResponse(WalkingPadStats().to_dict())


@app.post("/api/start")
async def api_start():
    if not controller or not controller.connected:
        return JSONResponse({"status": "error", "message": "Not connected"}, status_code=503)
    await controller.start()
    return JSONResponse({"status": "ok"})


@app.post("/api/stop")
async def api_stop():
    if not controller or not controller.connected:
        return JSONResponse({"status": "error", "message": "Not connected"}, status_code=503)
    await controller.stop()
    return JSONResponse({"status": "ok"})


@app.post("/api/speed/{kmh}")
async def api_speed(kmh: float):
    if not controller or not controller.connected:
        return JSONResponse({"status": "error", "message": "Not connected"}, status_code=503)
    if kmh < 0.5 or kmh > 6.0:
        return JSONResponse(
            {"status": "error", "message": "Speed must be between 0.5 and 6.0 km/h"},
            status_code=400,
        )
    await controller.set_speed(kmh)
    return JSONResponse({"status": "ok", "speed": round(kmh, 1)})


# --- WebSocket ---


async def broadcast_stats() -> None:
    """Send current stats to all connected WebSocket clients."""
    if not controller:
        return
    data = json.dumps(controller.stats.to_dict())
    dead: list[WebSocket] = []
    for ws in ws_clients:
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    logger.info("WebSocket client connected (%d total)", len(ws_clients))

    # Send current stats immediately
    if controller:
        await ws.send_text(json.dumps(controller.stats.to_dict()))

    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(ws_clients))


# --- Background tasks ---


async def _reconnect_loop(mac: str) -> None:
    """Connect to WalkingPad and auto-reconnect on connection loss."""
    global controller
    while True:
        try:
            if controller is None:
                controller = WalkingPadController(mac, on_status=lambda s: None)
            if not controller.connected:
                logger.info("Connecting to WalkingPad...")
                await controller.connect()
                logger.info("Connected successfully!")
        except Exception as e:
            logger.warning("Connection failed: %s — retrying in 10s", e)
        await asyncio.sleep(10)


async def _polling_loop() -> None:
    """Poll WalkingPad status and broadcast to WebSocket clients."""
    # Wait for initial connection before starting to poll
    while not (controller and controller.connected):
        await asyncio.sleep(1)

    while True:
        if controller and controller.connected:
            try:
                await controller.request_status()
                await asyncio.sleep(0.2)  # Wait for notification response
                await broadcast_stats()
            except Exception as e:
                logger.warning("Polling error: %s", e)
        await asyncio.sleep(_poll_interval)


# --- CLI & main ---


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="WalkingPad OBS Overlay Server")
    parser.add_argument("--mac", required=True, help="WalkingPad BLE MAC address")
    parser.add_argument("--host", default="0.0.0.0", help="Server host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8777, help="Server port (default: 8777)")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Status polling interval in seconds (default: 1.0)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    global _poll_interval
    _poll_interval = args.poll_interval

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    print()
    print(f"  WalkingPad OBS Overlay running at http://127.0.0.1:{args.port}")
    print(f"     Dashboard:          http://127.0.0.1:{args.port}/")
    print(f"     OBS Browser Source:  http://127.0.0.1:{args.port}/overlay")
    print(f"     API stats:           http://127.0.0.1:{args.port}/api/stats")
    print()

    async def _run() -> None:
        # Start background tasks
        asyncio.create_task(_reconnect_loop(args.mac))
        asyncio.create_task(_polling_loop())

        # Run uvicorn
        config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    asyncio.run(_run())
