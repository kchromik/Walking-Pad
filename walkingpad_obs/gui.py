"""Tkinter GUI for WalkingPad OBS Overlay."""

import asyncio
import logging
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk

from .config import get_last_mac, set_last_mac
from .protocol import WalkingPadController, scan_for_walkingpads
from . import server

logger = logging.getLogger(__name__)

# Colors matching the web UI
BG = "#0c0c10"
BG_CARD = "#16161e"
BG_INPUT = "#1e1e2a"
FG = "#e8e8ec"
FG_DIM = "#666"
GREEN = "#22d68a"
CYAN = "#5be0f8"
PURPLE = "#c084fc"
ORANGE = "#f8945b"
RED = "#f44"
BORDER = "#2a2a3a"


class WalkingPadApp:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("WalkingPad Control")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.geometry("420x700")

        # State
        self.controller: WalkingPadController | None = None
        self.devices: list[dict] = []
        self.is_connected = False
        self.is_scanning = False
        self.server_running = False
        self.stats_queue: queue.Queue = queue.Queue()

        # Async event loop in background thread
        self.loop = asyncio.new_event_loop()
        self._async_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._async_thread.start()

        self._build_ui()
        self._load_last_device()
        self._poll_stats()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _run_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _schedule(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    # --- UI Construction ---

    def _build_ui(self):
        pad = {"padx": 12, "pady": 4}
        self.root.grid_columnconfigure(0, weight=1)

        # Header
        hdr = tk.Frame(self.root, bg=BG)
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        tk.Label(hdr, text="WalkingPad Control", font=("sans-serif", 16, "bold"),
                 bg=BG, fg=FG).pack(side="left")
        self.conn_label = tk.Label(hdr, text="Nicht verbunden", font=("sans-serif", 9),
                                   bg=BG, fg=RED)
        self.conn_label.pack(side="right")

        # Device section
        dev = tk.LabelFrame(self.root, text="Gerät", font=("sans-serif", 9),
                            bg=BG_CARD, fg=FG_DIM, bd=1, relief="solid",
                            highlightbackground=BORDER, highlightthickness=1)
        dev.grid(row=1, column=0, sticky="ew", **pad)
        dev.grid_columnconfigure(0, weight=1)

        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(dev, textvariable=self.device_var,
                                          state="readonly", height=6)
        self.device_combo.grid(row=0, column=0, sticky="ew", padx=6, pady=6)

        btn_frame = tk.Frame(dev, bg=BG_CARD)
        btn_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))
        self.scan_btn = tk.Button(btn_frame, text="Scannen", command=self._on_scan,
                                   bg=BG_INPUT, fg=FG, activebackground=BORDER,
                                   activeforeground=FG, bd=0, padx=12, pady=4,
                                   font=("sans-serif", 9))
        self.scan_btn.pack(side="left", padx=(0, 6))
        self.connect_btn = tk.Button(btn_frame, text="Verbinden", command=self._on_connect,
                                      bg=GREEN, fg=BG, activebackground="#1ab373",
                                      activeforeground=BG, bd=0, padx=12, pady=4,
                                      font=("sans-serif", 9, "bold"))
        self.connect_btn.pack(side="left")

        # Stats grid
        stats = tk.Frame(self.root, bg=BG)
        stats.grid(row=2, column=0, sticky="ew", **pad)
        stats.grid_columnconfigure(0, weight=1)
        stats.grid_columnconfigure(1, weight=1)

        self.stat_labels = {}
        self._make_stat(stats, "time", "Zeit", "00:00", GREEN, 0, 0)
        self._make_stat(stats, "speed", "Speed", "0.0 km/h", CYAN, 0, 1)
        self._make_stat(stats, "steps", "Schritte", "0", PURPLE, 1, 0)
        self._make_stat(stats, "cal", "Kalorien", "0 kcal", ORANGE, 1, 1)
        self._make_stat(stats, "dist", "Distanz", "0.00 km", FG, 2, 0, colspan=2)

        # Speed section
        spd = tk.LabelFrame(self.root, text="Geschwindigkeit", font=("sans-serif", 9),
                             bg=BG_CARD, fg=FG_DIM, bd=1, relief="solid",
                             highlightbackground=BORDER, highlightthickness=1)
        spd.grid(row=3, column=0, sticky="ew", **pad)
        spd.grid_columnconfigure(0, weight=1)

        self.speed_label = tk.Label(spd, text="3.0 km/h", font=("monospace", 14, "bold"),
                                     bg=BG_CARD, fg=CYAN)
        self.speed_label.grid(row=0, column=0, pady=(6, 2))

        self.speed_var = tk.IntVar(value=30)
        self.speed_slider = tk.Scale(spd, from_=5, to=60, orient="horizontal",
                                      variable=self.speed_var, showvalue=False,
                                      bg=BG_CARD, fg=CYAN, troughcolor=BG_INPUT,
                                      activebackground=CYAN, highlightthickness=0,
                                      bd=0, length=350, sliderlength=20,
                                      command=self._on_slider)
        self.speed_slider.grid(row=1, column=0, padx=12, sticky="ew")

        presets = tk.Frame(spd, bg=BG_CARD)
        presets.grid(row=2, column=0, pady=(4, 8), padx=12)
        for val in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]:
            b = tk.Button(presets, text=str(val), width=4,
                          command=lambda v=val: self._set_speed(v),
                          bg=BG_INPUT, fg=FG, activebackground=CYAN,
                          activeforeground=BG, bd=0, font=("monospace", 9))
            b.pack(side="left", padx=2)

        # Action buttons
        actions = tk.Frame(self.root, bg=BG)
        actions.grid(row=4, column=0, sticky="ew", **pad)
        actions.grid_columnconfigure(0, weight=1)
        actions.grid_columnconfigure(1, weight=1)

        self.start_btn = tk.Button(actions, text="▶  Start", command=self._on_start,
                                    bg="#1a3a2a", fg=GREEN, activebackground=GREEN,
                                    activeforeground=BG, bd=0, pady=10,
                                    font=("sans-serif", 11, "bold"), state="disabled")
        self.start_btn.grid(row=0, column=0, sticky="ew", padx=(0, 4))

        self.stop_btn = tk.Button(actions, text="■  Stop", command=self._on_stop,
                                   bg="#3a1a1a", fg=RED, activebackground=RED,
                                   activeforeground=BG, bd=0, pady=10,
                                   font=("sans-serif", 11, "bold"), state="disabled")
        self.stop_btn.grid(row=0, column=1, sticky="ew", padx=(4, 0))

        # Server info
        info = tk.Frame(self.root, bg=BG)
        info.grid(row=5, column=0, sticky="ew", padx=12, pady=(8, 0))
        self.server_label = tk.Label(info, text="Server: nicht gestartet",
                                      font=("monospace", 8), bg=BG, fg=FG_DIM, anchor="w")
        self.server_label.pack(fill="x")
        self.overlay_label = tk.Label(info, text="",
                                       font=("monospace", 8), bg=BG, fg=FG_DIM, anchor="w")
        self.overlay_label.pack(fill="x")

        # Log
        log_frame = tk.LabelFrame(self.root, text="Log", font=("sans-serif", 9),
                                   bg=BG_CARD, fg=FG_DIM, bd=1, relief="solid",
                                   highlightbackground=BORDER, highlightthickness=1)
        log_frame.grid(row=6, column=0, sticky="nsew", padx=12, pady=(8, 12))
        self.root.grid_rowconfigure(6, weight=1)

        self.log_text = tk.Text(log_frame, height=6, bg=BG_CARD, fg=FG_DIM,
                                 font=("monospace", 9), bd=0, wrap="word",
                                 state="disabled", highlightthickness=0)
        self.log_text.pack(fill="both", expand=True, padx=4, pady=4)
        self.log_text.tag_configure("ok", foreground=GREEN)
        self.log_text.tag_configure("err", foreground=RED)
        self.log_text.tag_configure("info", foreground=FG_DIM)

    def _make_stat(self, parent, key, label, default, color, row, col, colspan=1):
        frame = tk.Frame(parent, bg=BG_CARD, highlightbackground=BORDER,
                         highlightthickness=1, padx=12, pady=8)
        frame.grid(row=row, column=col, columnspan=colspan, sticky="ew", padx=3, pady=3)
        val = tk.Label(frame, text=default, font=("monospace", 20, "bold"),
                       bg=BG_CARD, fg=color)
        val.pack()
        tk.Label(frame, text=label, font=("sans-serif", 8), bg=BG_CARD, fg=FG_DIM).pack()
        self.stat_labels[key] = val

    # --- Logging ---

    def _log(self, msg, tag="info"):
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{ts}  {msg}\n", tag)
        # Keep max 50 lines
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 50:
            self.log_text.delete("1.0", f"{lines - 50}.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # --- Device management ---

    def _load_last_device(self):
        mac = get_last_mac()
        if mac:
            self.device_combo["values"] = [mac]
            self.device_var.set(mac)

    def _on_scan(self):
        if self.is_scanning:
            return
        self.is_scanning = True
        self.scan_btn.configure(text="Scanne...", state="disabled")
        self._log("Scanne nach WalkingPad Geräten...")
        self._schedule(self._async_scan())

    async def _async_scan(self):
        try:
            devices = await scan_for_walkingpads(timeout=8.0)
            self.devices = devices
            entries = [f"{d['name']}  ({d['address']})" for d in devices]
            # Update combo in GUI thread
            self.root.after(0, self._update_device_list, entries)
        except Exception as e:
            self.root.after(0, self._log, f"Scan-Fehler: {e}", "err")
        finally:
            self.root.after(0, self._scan_done)

    def _update_device_list(self, entries):
        self.device_combo["values"] = entries
        if entries:
            self.device_var.set(entries[0])
            self._log(f"{len(entries)} Gerät(e) gefunden", "ok")
        else:
            self._log("Keine Geräte gefunden. Ist das Pad an?", "err")

    def _scan_done(self):
        self.is_scanning = False
        self.scan_btn.configure(text="Scannen", state="normal")

    def _get_selected_mac(self) -> str | None:
        val = self.device_var.get()
        if not val:
            return None
        # Extract MAC from "Name  (MAC)" format
        if "(" in val:
            return val.split("(")[-1].rstrip(")")
        return val.strip()

    # --- Connect / Disconnect ---

    def _on_connect(self):
        if self.is_connected:
            self._schedule(self._async_disconnect())
            return

        mac = self._get_selected_mac()
        if not mac:
            self._log("Kein Gerät ausgewählt", "err")
            return

        self.connect_btn.configure(text="Verbinde...", state="disabled")
        self._log(f"Verbinde mit {mac}...")
        self._schedule(self._async_connect(mac))

    async def _async_connect(self, mac: str):
        try:
            # Create controller with callback that feeds the stats queue
            self.controller = WalkingPadController(mac, on_status=self._on_ble_status)
            await self.controller.connect()

            # Register controller with the server module
            server.set_controller(self.controller)

            # Start web server if not running
            if not self.server_running:
                self.server_running = True
                asyncio.ensure_future(server.start_server(), loop=self.loop)
                self.root.after(0, self._update_server_info)

            set_last_mac(mac)
            self.root.after(0, self._set_connected, True)
            self.root.after(0, self._log, "Verbunden!", "ok")
        except Exception as e:
            self.root.after(0, self._log, f"Verbindungsfehler: {e}", "err")
            self.root.after(0, self._set_connected, False)

    async def _async_disconnect(self):
        try:
            if self.controller:
                await self.controller.disconnect()
                server.set_controller(None)
            self.root.after(0, self._set_connected, False)
            self.root.after(0, self._log, "Getrennt", "info")
        except Exception as e:
            self.root.after(0, self._log, f"Fehler beim Trennen: {e}", "err")

    def _set_connected(self, connected: bool):
        self.is_connected = connected
        if connected:
            self.conn_label.configure(text="Verbunden", fg=GREEN)
            self.connect_btn.configure(text="Trennen", bg=RED, state="normal",
                                        activebackground="#c33")
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="normal")
        else:
            self.conn_label.configure(text="Nicht verbunden", fg=RED)
            self.connect_btn.configure(text="Verbinden", bg=GREEN, state="normal",
                                        activebackground="#1ab373")
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="disabled")

    def _update_server_info(self):
        self.server_label.configure(text="Server: http://127.0.0.1:8777", fg=FG)
        self.overlay_label.configure(text="OBS:    http://127.0.0.1:8777/overlay", fg=FG)
        self._log("Webserver gestartet auf Port 8777", "ok")

    # --- BLE status callback ---

    async def _on_ble_status(self, stats):
        """Called from async BLE thread when new stats arrive."""
        self.stats_queue.put(stats.to_dict())
        await server.broadcast_stats()

    def _poll_stats(self):
        """Poll the stats queue from the GUI thread."""
        try:
            while True:
                data = self.stats_queue.get_nowait()
                self._update_display(data)
        except queue.Empty:
            pass
        # Also check connection state
        if self.controller and not self.controller.connected and self.is_connected:
            self._set_connected(False)
            self._log("Verbindung verloren", "err")
        self.root.after(200, self._poll_stats)

    def _update_display(self, data: dict):
        self.stat_labels["time"].configure(text=data.get("time_formatted", "00:00"))
        self.stat_labels["speed"].configure(text=f"{data.get('speed_kmh', 0):.1f} km/h")
        steps = data.get("steps", 0)
        self.stat_labels["steps"].configure(text=f"{steps:,}".replace(",", "."))
        self.stat_labels["cal"].configure(text=f"{data.get('calories', 0)} kcal")
        self.stat_labels["dist"].configure(text=f"{data.get('distance_km', 0):.2f} km")

        # Update connection label with running state
        if data.get("is_running"):
            self.conn_label.configure(text="Läuft", fg=GREEN)
        elif data.get("connected"):
            self.conn_label.configure(text="Verbunden", fg=GREEN)

    # --- Controls ---

    def _on_slider(self, val):
        kmh = int(val) / 10.0
        self.speed_label.configure(text=f"{kmh:.1f} km/h")
        if self.is_connected:
            self._schedule(self._async_set_speed(kmh))

    def _set_speed(self, kmh: float):
        self.speed_var.set(int(kmh * 10))
        self.speed_label.configure(text=f"{kmh:.1f} km/h")
        if self.is_connected:
            self._schedule(self._async_set_speed(kmh))

    async def _async_set_speed(self, kmh: float):
        try:
            if self.controller and self.controller.connected:
                await self.controller.set_speed(kmh)
        except Exception as e:
            self.root.after(0, self._log, f"Speed-Fehler: {e}", "err")

    def _on_start(self):
        if self.is_connected:
            self._log("Starte Belt...", "info")
            self._schedule(self._async_start())

    def _on_stop(self):
        if self.is_connected:
            self._log("Stoppe Belt...", "info")
            self._schedule(self._async_stop())

    async def _async_start(self):
        try:
            if self.controller and self.controller.connected:
                await self.controller.start()
                self.root.after(0, self._log, "Belt gestartet", "ok")
        except Exception as e:
            self.root.after(0, self._log, f"Start-Fehler: {e}", "err")

    async def _async_stop(self):
        try:
            if self.controller and self.controller.connected:
                await self.controller.stop()
                self.root.after(0, self._log, "Belt gestoppt", "ok")
        except Exception as e:
            self.root.after(0, self._log, f"Stop-Fehler: {e}", "err")

    # --- Lifecycle ---

    def _on_close(self):
        if self.controller and self.controller.connected:
            self._schedule(self.controller.disconnect())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    app = WalkingPadApp()
    app.run()
