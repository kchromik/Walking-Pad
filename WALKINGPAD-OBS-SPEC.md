# WalkingPad OBS Overlay – Projektspezifikation

## Überblick

Baue einen lokalen Webservice, der sich per Bluetooth Low Energy (BLE) mit einem **KingSmith WalkingPad A1 Pro** Laufband verbindet, Live-Daten ausliest (Schritte, Distanz, Zeit, Geschwindigkeit) und diese über ein **OBS Browser Source Overlay** in einen Livestream einblendet. Zusätzlich soll ein **Web-Dashboard** die Steuerung des Laufbands ermöglichen (Start, Stop, Geschwindigkeit).

Das System läuft auf **CachyOS (Arch Linux)** mit Python.

---

## Architektur

```
WalkingPad A1 Pro ──BLE/GATT──► Python Server (FastAPI + bleak)
                                    ├── GET  /           → Web Dashboard (Steuerung + Stats)
                                    ├── GET  /overlay    → OBS Browser Source (nur Stats-Anzeige)
                                    ├── WS   /ws         → WebSocket (Live-Stats-Stream)
                                    ├── GET  /api/stats  → JSON (aktueller Status)
                                    ├── POST /api/start  → Belt starten
                                    ├── POST /api/stop   → Belt stoppen
                                    └── POST /api/speed/{kmh} → Geschwindigkeit setzen
```

---

## Technologie-Stack

- **Python 3.12+**
- **bleak** – BLE/GATT Kommunikation (pure Python, keine C-Dependencies)
- **FastAPI** – Webserver mit WebSocket-Support
- **uvicorn** – ASGI Server
- Keine Datenbank, kein Frontend-Framework – alles vanilla HTML/CSS/JS
- Kein Docker – läuft direkt auf dem Host

---

## Projektstruktur

```
walkingpad-obs/
├── requirements.txt
├── README.md
├── walkingpad_obs/
│   ├── __init__.py
│   ├── __main__.py          # Entry point: python -m walkingpad_obs
│   ├── protocol.py          # BLE-Protokoll, GATT-Kommunikation, Paket-Parsing
│   ├── server.py            # FastAPI App, WebSocket, REST API, CLI args
│   ├── scan.py              # Helper: BLE-Scan nach WalkingPad Geräten
│   ├── overlay.html         # OBS Browser Source Overlay
│   └── dashboard.html       # Web-Dashboard zur Steuerung
```

---

## BLE-Protokoll (KingSmith WalkingPad A1 Pro)

### GATT Service & Characteristics

| UUID | Funktion |
|------|----------|
| `0000fe00-0000-1000-8000-00805f9b34fb` | Service UUID |
| `0000fe01-0000-1000-8000-00805f9b34fb` | Write Characteristic (Befehle senden) |
| `0000fe02-0000-1000-8000-00805f9b34fb` | Notify Characteristic (Antworten empfangen) |

### Paketformat

Jedes Paket hat folgende Struktur:

```
[0xF7] [0xA2] [CMD] [...PARAMS] [CHECKSUM] [0xFD]
```

- **Start-Byte**: `0xF7`
- **Header**: `0xA2`
- **CMD**: Kommando-Byte
- **Params**: Variable Länge
- **Checksum**: `(sum aller Bytes von 0xA2 bis letztem Param) & 0xFF`
- **End-Byte**: `0xFD`

### Befehle (Write → `fe01`)

| Befehl | CMD | Params | Beschreibung |
|--------|-----|--------|--------------|
| Status abfragen | `0x00` | keine | Aktuellen Status anfordern |
| Geschwindigkeit | `0x01` | `[speed]` | Speed in 0.1 km/h (z.B. `35` = 3.5 km/h), Range: 5–60 |
| Modus setzen | `0x02` | `[mode]` | 0=Standby, 1=Manual, 2=Auto |
| Start | `0x04` | `[0x01]` | Belt starten |
| Stop | `0x04` | `[0x02]` | Belt stoppen |

### Status-Antwort (Notify ← `fe02`)

Aktueller Status (CMD `0xA2`, mindestens 18 Bytes):

| Byte-Index | Feld | Format |
|------------|------|--------|
| 0 | Start (`0xF7`) | — |
| 1 | Header (`0xA2`) | — |
| 2 | CMD (`0xA2` = aktueller Status) | — |
| 3 | State | `0`=Standby, `1`=Running, `2`=Starting, `5`=Idle, `6`=Paused |
| 4–5 | Speed | Big-endian uint16, ÷10 für km/h |
| 6 | Mode | `0`=Standby, `1`=Manual, `2`=Auto |
| 7–9 | Zeit | Big-endian uint24, Sekunden |
| 10–12 | Distanz | Big-endian uint24, ÷100 für km |
| 13–15 | Schritte | Big-endian uint24 |
| -2 | Checksum | — |
| -1 | End (`0xFD`) | — |

### Wichtige Einschränkungen

- **Nur eine BLE-Verbindung gleichzeitig** – die Smartphone-App muss getrennt sein
- Das Pad speichert den letzten Lauf-Status nur temporär (überlebt keinen Stromausfall)
- BLE-Name des Geräts ist typischerweise `KS-ST-A1P`
- Notifications kommen als Fragmente – es muss ein **Paket-Buffer** implementiert werden, der auf Start-Byte `0xF7` und End-Byte `0xFD` prüft

### Referenzen

- Protokoll-Header: https://github.com/DorianRudolph/QWalkingPad/blob/master/Protocol.h
- Python-Implementierung: https://github.com/ph4r05/ph4-walkingpad

---

## Server (`server.py`)

### CLI-Interface

```bash
# Server starten
python -m walkingpad_obs --mac "AA:BB:CC:DD:EE:FF"

# Optionale Flags
python -m walkingpad_obs \
  --mac "AA:BB:CC:DD:EE:FF" \
  --host 0.0.0.0 \
  --port 8777 \
  --poll-interval 1.0 \
  --verbose
```

### Verhalten

- Beim Start automatisch BLE-Verbindung zum WalkingPad herstellen
- **Auto-Reconnect**: Bei Verbindungsabbruch alle 5 Sekunden erneut versuchen
- **Status-Polling**: Alle `--poll-interval` Sekunden den Status vom Pad abfragen
- **WebSocket-Broadcast**: Jede Status-Änderung an alle verbundenen WebSocket-Clients senden
- Beim Start im Terminal die URLs ausgeben:
  ```
  🚀 WalkingPad OBS Overlay running at http://127.0.0.1:8777
     Dashboard:          http://127.0.0.1:8777/
     OBS Browser Source:  http://127.0.0.1:8777/overlay
     API stats:           http://127.0.0.1:8777/api/stats
  ```

### REST API

| Route | Method | Beschreibung | Response |
|-------|--------|--------------|----------|
| `/` | GET | Dashboard HTML | HTML |
| `/overlay` | GET | OBS Overlay HTML | HTML |
| `/api/stats` | GET | Aktueller Status | `{ distance_km, time_seconds, time_formatted, steps, speed_kmh, state, state_name, mode, mode_name, calories, connected, is_running }` |
| `/api/start` | POST | Belt starten | `{ status: "ok" }` |
| `/api/stop` | POST | Belt stoppen | `{ status: "ok" }` |
| `/api/speed/{kmh}` | POST | Speed setzen (0.5–6.0) | `{ status: "ok", speed: float }` |

### WebSocket `/ws`

- Nach Verbindung sofort aktuellen Status senden
- Bei jedem Status-Update JSON-Broadcast an alle Clients
- Keep-alive: Client sendet `"ping"`, Server antwortet `"pong"`
- Auto-Reconnect clientseitig

### Kalorien-Schätzung

Einfache Formel: `~55 kcal pro km`, mit 10% Bonus bei Speed > 4.0 km/h. Wird serverseitig aus Distanz berechnet.

---

## BLE Scanner (`scan.py`)

```bash
python -m walkingpad_obs.scan
```

- Scannt 10 Sekunden nach BLE-Geräten
- Filtert nach Namen die `KS-` oder `WALKINGPAD` enthalten
- Gibt Name, MAC-Adresse und RSSI aus
- Hinweis wenn nichts gefunden: "Pad muss an sein und darf nicht mit App verbunden sein"

---

## OBS Overlay (`overlay.html`)

### Zweck

Wird als OBS **Browser Source** eingebunden (800×200 px). Zeigt nur die Stats, keine Steuerung.

### Design-Anforderungen

- **Transparenter Hintergrund** (OBS rendert den Hintergrund weg)
- Dunkles Glasmorphism-Design mit halbtransparentem Hintergrund (`rgba(12, 12, 16, 0.85)`)
- Abgerundete Ecken (16px Border-Radius)
- **Horizontales Layout**: Alle Stats nebeneinander in einer Zeile
- Subtile Trennlinien (Divider) zwischen den Stats

### Angezeigte Werte

| Stat | Icon | Farbe | Format |
|------|------|-------|--------|
| Zeit | ⏱ | Grün `#22d68a` | `MM:SS` oder `H:MM:SS` |
| Distanz | 📏 | Weiß `#e8e8ec` | `0.00 km` |
| Schritte | 👟 | Lila `#c084fc` | `1,234` (mit Tausender-Trenner) |
| Geschwindigkeit | ⚡ | Cyan `#5be0f8` | `0.0 km/h` |
| Kalorien | 🔥 | Orange `#f8945b` | `0 kcal` |

### Fonts

- Werte: **JetBrains Mono** (Bold, 26px, tabular-nums)
- Labels: **Outfit** (10px, uppercase, letter-spacing)
- Via Google Fonts einbinden

### Animationen

- **Slide-in** beim Laden (translateY + scale, cubic-bezier)
- **Bump-Animation** bei Wertänderungen (kurzes scale auf 1.08)
- **Pulsierender Status-Dot** (oben links, 6px): Grün + Glow wenn verbunden, Rot wenn getrennt
- **Speed-Fill-Bar**: Hintergrund der Speed-Karte füllt sich proportional zur Geschwindigkeit (max 6 km/h = 100%)
- **Active-Bar**: Kleine leuchtende Linie unter der Speed-Karte wenn das Band läuft

### Zustände

- **Disconnected**: Gesamtes Overlay auf 50% Opacity, alle Werte grau
- **Connected/Idle**: Volle Opacity, grüner Dot, Werte bei 0
- **Running**: Wie Connected + Speed-Bar aktiv + Active-Line unter Speed

### WebSocket-Verbindung

- Verbindet zu `ws://{host}/ws`
- Auto-Reconnect mit exponential backoff (1s → max 10s)
- Keep-alive Ping alle 30s

---

## Web Dashboard (`dashboard.html`)

### Zweck

Lokales Control Panel im Browser zum Steuern des WalkingPads und Monitoring der Stats. Wird unter `/` ausgeliefert.

### Design-Anforderungen

- Dunkles UI (Background `#0c0c10`)
- Zentriertes Card-Layout, max 480px breit
- Gleiche Font-Familie wie Overlay (JetBrains Mono + Outfit)
- Deutsche Labels/Texte

### Layout (von oben nach unten)

#### 1. Header
- Icon (🚶 in grünem Badge)
- Titel: "WalkingPad Control"
- Connection Badge: Grün "Verbunden"/"Läuft" oder Rot "Pad nicht verbunden"/"Server getrennt"

#### 2. Stats-Grid (2 Spalten)
- Zeit (grün) | Geschwindigkeit (cyan)
- Schritte (lila) | Kalorien (orange)
- Distanz (volle Breite, weiß)
- Jede Stat in einer Card mit Label oben, großem Wert unten
- Gleiche Farben wie im Overlay

#### 3. Geschwindigkeit-Sektion
- Label "Geschwindigkeit einstellen" links, aktueller Wert rechts
- **Range-Slider** (0.5–6.0 km/h, 0.1er Schritte, also min=5 max=60 step=1 intern)
- Custom Slider-Thumb: Cyan, rund, mit Glow
- **6 Preset-Buttons** darunter: 1.0, 2.0, 3.0, 4.0, 5.0, 6.0
- Aktiver Preset wird hervorgehoben
- API-Call wird **debounced** (300ms) beim Slider

#### 4. Action-Buttons (2 Spalten)
- **▶ Start**: Grüner Hintergrund, ruft `POST /api/start`
- **■ Stop**: Roter Hintergrund, ruft `POST /api/stop`
- Beide disabled wenn Pad nicht verbunden

#### 5. Log-Bereich
- Scrollbares Log am unteren Rand (max 120px Höhe)
- JetBrains Mono, 11px
- Zeitstempel (gedimmt) + Nachricht
- Farbcodiert: `.ok` = grün, `.err` = rot
- Max 50 Einträge

### WebSocket-Verbindung

- Identisch zum Overlay: `ws://{host}/ws`, Auto-Reconnect (2s), Ping/Pong
- Bei Verbindungsverlust: Badge wird rot, Buttons deaktiviert

---

## requirements.txt

```
bleak>=0.21.0
fastapi>=0.110.0
uvicorn[standard]>=0.29.0
websockets>=12.0
```

---

## Zusammenfassung der Endpunkte

| URL | Zweck | Für wen |
|-----|-------|---------|
| `http://127.0.0.1:8777/` | Dashboard zum Steuern | Im Browser öffnen |
| `http://127.0.0.1:8777/overlay` | Stream-Overlay | OBS Browser Source (800×200) |
| `http://127.0.0.1:8777/ws` | Live-Daten WebSocket | Overlay + Dashboard |
| `http://127.0.0.1:8777/api/stats` | Status JSON | Externe Integrationen |
| `http://127.0.0.1:8777/api/start` | Belt starten | Dashboard / Stream Deck |
| `http://127.0.0.1:8777/api/stop` | Belt stoppen | Dashboard / Stream Deck |
| `http://127.0.0.1:8777/api/speed/{kmh}` | Speed setzen | Dashboard / Stream Deck |
