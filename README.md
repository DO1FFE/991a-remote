# 991a-remote

Dieses Projekt stellt eine einfach zu bedienende Weboberfläche zur Fernsteuerung eines Yaesu FT‑991A bereit. Der Server kann direkt am Funkgerät laufen oder auf einen separaten Steuerungsdienst zugreifen.

## Aufbau

- `server/flask_server.py` – Flask-Anwendung mit Login-Schutz und Weboberfläche
- `server/ft991a_ws_server.py` – schlanker WebSocket-Server zur CAT-Steuerung auf dem Windows‑Rechner
- `server/templates/` – HTML-Vorlagen für Login und Steuerungsseite
- `requirements.txt` – benötigte Python-Pakete

## Installation

1. Python (ab Version 3.9) installieren.
2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```
3. Optional: Serielle Schnittstelle und Zugangsdaten können beim Start der Anwendung angegeben werden.

## Nutzung

### Server am Funkgerät (Windows)

1. Auf dem Windows‑Rechner mit angeschlossenem FT‑991A den Steuerungsdienst starten:
   ```bash
   python server/ft991a_ws_server.py --serial-port COM3
   ```
   Der COM‑Port ist ggf. anzupassen. Der Dienst lauscht auf Port 9001 für WebSocket‑Verbindungen.

### Flask‑Server auf dem Client (Linux)

1. Auf dem Linux‑Rechner die Weboberfläche starten und mit dem obigen Dienst verbinden:
   ```bash
   python server/flask_server.py --server ws://<windows-ip>:9001 --username admin --password secret
   ```
   Die Anwendung läuft auf Port 8000 (anpassbar mit `--http-port`) und verlangt beim Aufruf im Browser Benutzername und Passwort.
2. Nach erfolgreichem Login können Frequenz, Modus und PTT gesteuert werden. Zudem steht ein Feld für beliebige CAT-Befehle zur Verfügung.

Die Implementierung bildet nur grundlegende Funktionen ab und kann als Grundlage für eigene Erweiterungen dienen.
