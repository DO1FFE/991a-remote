# 991a-remote

Dieses Projekt stellt eine einfach zu bedienende Weboberfläche zur Fernsteuerung eines Yaesu FT‑991A bereit. Der Server kann direkt am Funkgerät laufen oder auf einen separaten Steuerungsdienst zugreifen.

## Aufbau

- `flask_server.py` – Flask-Anwendung mit Login-Schutz und Weboberfläche
- `trx/ft991a_ws_server.py` – schlanker WebSocket-Server zur CAT-Steuerung auf dem Windows‑Rechner. Er meldet sich mit Benutzerdaten am Flask-Server an und kann wahlweise einen TRX bereitstellen oder als Operator verbinden.
- `templates/` – HTML-Vorlagen für Login und Steuerungsseite
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
   eine Verbindung zum Flask‑Server aufbauen. Dabei melden Sie sich mit Ihren Benutzerdaten an:
   ```bash
   python trx/ft991a_ws_server.py --serial-port COM3 \
       --connect ws://991a.lima11.de:8084/ws/rig \
       --callsign MYCALL --username MYCALL --password secret --mode trx
   ```
   Der COM‑Port ist ggf. anzupassen. Verbinden sich mehrere Stationen, kann auf der Weboberfläche eine davon ausgewählt werden.

### Nutzung als Operator

Möchten Sie mit dem Programm selbst einen entfernten TRX bedienen, starten Sie es ohne serielle Schnittstelle und melden sich als Operator an:

```bash
python trx/ft991a_ws_server.py --connect ws://991a.lima11.de:8084/ws/rig \
    --username MYCALL --password secret --mode operator
```

### Flask‑Server auf dem Client (Linux)

1. Auf dem Linux‑Rechner die Weboberfläche starten. Der Server wartet auf eine eingehende Verbindung des Steuerungsdienstes:
   ```bash
   python flask_server.py
   ```
   Mit dem Parameter `--server` kann optional weiterhin ein externer Dienst angesprochen werden. Die Anwendung läuft auf Port 8084 (anpassbar mit `--http-port`).
   Beim ersten Start existiert lediglich der Benutzer `admin` mit dem Passwort `admin`. Dieses Konto muss sich nach dem Login umbenennen und ein neues Passwort vergeben.
    Weitere Benutzer können sich anschließend selbst registrieren und müssen vom Administrator freigeschaltet werden, bevor sie das Gerät bedienen dürfen.
    Nur Administratoren dürfen neue Benutzer freischalten oder ihnen das Recht zur Nutzung eines TRX erteilen.
   Über `--list-devices` lassen sich verfügbare Audio‑Geräte anzeigen. Mit
   `--input-device` und `--output-device` kann anschließend die gewünschte
   Geräte‑Nummer gewählt werden.
2. Benutzer registrieren sich über die Weboberfläche mit ihrem Rufzeichen und einem Passwort. Erst nach Freischaltung durch einen Administrator dürfen sie das Gerät als Operator bedienen. Bis dahin können sie lediglich im SWL-Modus zuhören.

Die Implementierung bildet nur grundlegende Funktionen ab und kann als Grundlage für eigene Erweiterungen dienen.

## Wichtige CAT-Befehle

| Befehl | Beschreibung |
| ------ | ------------ |
| `FAxxxxxxx;` | VFO-A Frequenz einstellen (lesen mit `FA;`) |
| `MDxx;` | Betriebsart einstellen (lesen mit `MD;`) |
| `TX;` | PTT aktivieren |
| `RX;` | PTT deaktivieren |
