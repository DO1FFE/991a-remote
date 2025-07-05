# 991a-remote

Dieses Projekt stellt eine einfach zu bedienende Weboberfläche zur Fernsteuerung eines Yaesu FT‑991A bereit. Der Server kann direkt am Funkgerät laufen oder auf einen separaten Steuerungsdienst zugreifen.

## Aufbau

- `server/flask_server.py` – Flask-Anwendung mit Login-Schutz und Weboberfläche
- `server/ft991a_ws_server.py` – schlanker WebSocket-Server zur CAT-Steuerung auf dem Windows‑Rechner; meldet sich mit einem frei wählbaren Rufzeichen
- `server/templates/` – HTML-Vorlagen für Login und Steuerungsseite
- `requirements.txt` – benötigte Python-Pakete

## Installation

1. Python (ab Version 3.9) installieren.
2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```
3. Optional: Serielle Schnittstelle, Audio-Geräte und Zugangsdaten können beim Start der Anwendung angegeben werden.

## Nutzung

### Server am Funkgerät (Windows)

1. Auf dem Windows‑Rechner mit angeschlossenem FT‑991A den Steuerungsdienst starten und
   eine Verbindung zum Flask‑Server aufbauen:
   ```bash
   python server/ft991a_ws_server.py --serial-port COM3 \
       --connect ws://991a.lima11.de:8000/ws/rig \
       --callsign MYCALL
   ```
   Der COM‑Port ist ggf. anzupassen.
   Das Rufzeichen wird an den Flask‑Server übertragen. Verbinden sich mehrere
   Stationen, kann auf der Weboberfläche eine davon ausgewählt werden.

### Flask‑Server auf dem Client (Linux)

1. Auf dem Linux‑Rechner die Weboberfläche starten. Der Server wartet auf eine eingehende Verbindung des Steuerungsdienstes:
   ```bash
   python server/flask_server.py --username admin --password secret
   ```
   Mit dem Parameter `--server` kann optional weiterhin ein externer Dienst angesprochen werden. Die Anwendung läuft auf Port 8000 (anpassbar mit `--http-port`) und verlangt beim Aufruf im Browser Benutzername und Passwort.
   Über `--list-devices` lassen sich verfügbare Audio‑Geräte anzeigen. Mit
   `--input-device` und `--output-device` kann anschließend die gewünschte
   Geräte‑Nummer gewählt werden.
2. Nach erfolgreichem Login kann sich jeder Benutzer mit einem frei wählbaren Nutzernamen anmelden. Pro angeschlossenem 991A kann genau ein Nutzer die Rolle des Operators übernehmen und das Gerät steuern. Alle weiteren eingeloggten Nutzer können den Audiostream im sogenannten SWL-Modus mithören.

Die Implementierung bildet nur grundlegende Funktionen ab und kann als Grundlage für eigene Erweiterungen dienen.

## Wichtige CAT-Befehle

| Befehl | Beschreibung |
| ------ | ------------ |
| `FAxxxxxxx;` | VFO-A Frequenz einstellen (lesen mit `FA;`) |
| `MDxx;` | Betriebsart einstellen (lesen mit `MD;`) |
| `TX;` | PTT aktivieren |
| `RX;` | PTT deaktivieren |
