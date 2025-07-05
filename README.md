# 991a-remote

Dieses Projekt stellt eine einfach zu bedienende Weboberfläche zur Fernsteuerung eines Yaesu FT‑991A bereit. Der gesamte Funktionsumfang ist im Server umgesetzt, so dass keine separaten Client‑Skripte mehr notwendig sind.

## Aufbau

- `server/flask_server.py` – Flask-Anwendung mit Login-Schutz, CAT-Steuerung und Audiobrücke per WebSocket
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

1. Den Server auf dem Rechner mit angeschlossenem FT‑991A starten:
   ```bash
   python server/flask_server.py --serial-port COM3 --username admin --password secret
   ```
   Der Parameter `--serial-port` muss an den verwendeten COM-Port angepasst werden. 
   Die Anwendung lauscht anschließend auf Port 8000 (anpassbar mit `--http-port`)
   und verlangt beim Aufruf im Browser Benutzername und Passwort.
2. Nach erfolgreichem Login können Frequenz, Modus und PTT gesteuert werden. 
   Zudem steht ein Feld für beliebige CAT-Befehle zur Verfügung. 
   Mit "Start Audio" wird eine bidirektionale Audioübertragung über WebSocket aufgebaut.

Die Implementierung bildet nur grundlegende Funktionen ab und kann als Grundlage für eigene Erweiterungen dienen.
