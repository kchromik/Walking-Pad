# WalkingPad OBS – Ralph Loop Kommando

## Vorbereitung

1. Spec-Datei (`WALKINGPAD-OBS-SPEC.md`) im Projektordner ablegen
2. Ralph Loop Plugin installiert haben
3. Im leeren Projektordner starten:

```bash
mkdir walkingpad-obs && cd walkingpad-obs
cp ~/path/to/WALKINGPAD-OBS-SPEC.md ./WALKINGPAD-OBS-SPEC.md
git init
claude
```

## Kommando

Dieses Kommando in Claude Code einfügen:

```
/ralph-loop:ralph-loop "
## Aufgabe

Baue das Projekt 'WalkingPad OBS Overlay' nach der Spezifikation in WALKINGPAD-OBS-SPEC.md.

Lies ZUERST die gesamte Datei WALKINGPAD-OBS-SPEC.md und arbeite sie Feature für Feature ab.

## Projektstruktur

Erstelle exakt diese Struktur:

walkingpad-obs/
├── requirements.txt
├── README.md
├── walkingpad_obs/
│   ├── __init__.py
│   ├── __main__.py
│   ├── protocol.py
│   ├── server.py
│   ├── scan.py
│   ├── overlay.html
│   └── dashboard.html

## Reihenfolge (eine Aufgabe pro Iteration)

1. requirements.txt anlegen (bleak, fastapi, uvicorn, websockets)
2. protocol.py – BLE-Protokoll: GATT UUIDs, Paketformat, Command Builder, Status Parser, WalkingPadController Klasse mit connect/disconnect/start/stop/set_speed/request_status, Paket-Buffer für fragmentierte BLE-Notifications, WalkingPadStats Dataclass mit to_dict(), scan_for_walkingpads() Funktion
3. scan.py – BLE Scanner Modul, aufrufbar via python -m walkingpad_obs.scan
4. server.py – FastAPI Server mit: allen REST-Routen laut Spec (/api/stats, /api/start, /api/stop, /api/speed/{kmh}), WebSocket /ws mit Broadcast, GET / für Dashboard, GET /overlay für OBS Overlay, CLI argparse (--mac, --host, --port, --poll-interval, --verbose), Auto-Reconnect Loop, Status-Polling Loop
5. __main__.py – Entry point für python -m walkingpad_obs
6. overlay.html – OBS Browser Source: transparenter Hintergrund, horizontales Layout (Zeit, Distanz, Schritte, Speed, Kalorien), JetBrains Mono + Outfit Fonts via Google Fonts, Farbschema exakt laut Spec (Grün/Cyan/Lila/Orange), Animationen (slide-in, bump bei Wertänderung, pulsierender Status-Dot, Speed-Fill-Bar), drei Zustände (Disconnected/Idle/Running), WebSocket Client mit Auto-Reconnect
7. dashboard.html – Web Dashboard: dunkles UI (#0c0c10), deutsche Labels, Stats-Grid (2 Spalten + volle Breite für Distanz), Speed-Slider (0.5-6.0 km/h, 0.1er Schritte) mit debounced API-Call (300ms), 6 Preset-Buttons, Start/Stop Buttons, Connection Badge, scrollbares Log (max 50 Einträge), WebSocket Client mit Auto-Reconnect
8. README.md mit Setup-Anleitung, OBS-Einrichtung, API-Doku
9. Review: Lies alle Dateien nochmal, prüfe auf Konsistenz zwischen Server-Routen und Frontend-WebSocket-URLs, verifiziere dass das BLE-Protokoll korrekt implementiert ist

## Regeln

- Lies WALKINGPAD-OBS-SPEC.md VOR jeder Iteration
- Arbeite pro Iteration NUR an EINER Aufgabe aus der Liste oben
- Nach jeder Datei: prüfe Syntax (python -c 'import ast; ast.parse(open(\"datei\").read())' für .py Dateien)
- Nutze KEINE externen Frontend-Frameworks – nur vanilla HTML/CSS/JS
- Alle HTML-Dateien sind self-contained (CSS + JS inline)
- Fonts via Google Fonts CDN
- Kein Docker, keine Datenbank
- Commit nach jeder abgeschlossenen Aufgabe mit aussagekräftiger Message
- Wenn alle 9 Aufgaben erledigt und verifiziert sind, output: <promise>COMPLETE</promise>

## Verifikation vor Abschluss

Bevor du COMPLETE ausgibst, stelle sicher:
- [ ] Alle Dateien aus der Projektstruktur existieren
- [ ] requirements.txt enthält alle 4 Dependencies
- [ ] protocol.py: GATT UUIDs stimmen, Paket-Builder mit Checksum, Status-Parser für alle Byte-Offsets
- [ ] server.py: Alle 7 Routen implementiert, WebSocket broadcast funktioniert
- [ ] overlay.html: WebSocket verbindet zu ws://{host}/ws, alle 5 Stats werden angezeigt
- [ ] dashboard.html: Alle API-Calls (/api/start, /api/stop, /api/speed/{kmh}), Slider + Presets
- [ ] Python-Dateien haben keine Syntax-Fehler
- [ ] __main__.py importiert und ruft server.main() auf
" --completion-promise "COMPLETE" --max-iterations 15
```
