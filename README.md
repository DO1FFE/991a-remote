# 991a-remote

Dieses Projekt stellt eine einfach zu bedienende Weboberfläche zur Fernsteuerung eines Yaesu FT‑991A bereit. Der Server kann direkt am Funkgerät laufen oder auf einen separaten Steuerungsdienst zugreifen.

## Aufbau

- `flask_server.py` – Flask-Anwendung mit Login-Schutz und Weboberfläche
- `trx/ft991a_ws_server.py` – schlanker WebSocket-Server zur CAT-Steuerung auf dem Windows‑Rechner. Er meldet sich mit Benutzerdaten am Flask-Server an und kann wahlweise einen TRX bereitstellen oder als Operator verbinden.
- `trx/trx_gui.py` – kleine Tkinter-Oberfläche zum Start des Dienstes mit gespeicherten Zugangsdaten.
- `templates/` – HTML-Vorlagen für Login und Steuerungsseite
- `requirements.txt` – benötigte Python-Pakete

## Installation

1. Python (ab Version 3.9) installieren.
2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```
3. Optional: Serielle Schnittstelle, Audio-Geräte und Zugangsdaten können beim Start der Anwendung angegeben werden.

## Benutzerrollen

Die Anwendung unterscheidet vier Hierarchiestufen:

1. **Admin** – hat volle Rechte und darf Benutzer freischalten.
2. **Operator** – darf einen TRX bedienen.
3. **SWL** – registrierter Benutzer ohne Freischaltung, kann nur zuhören.
4. **Nicht freigeschaltet** – Konto angelegt, aber noch nicht bestätigt.

Ein TRX lässt sich nur mit der Rolle *Operator* oder *Admin* steuern.
Administratoren besitzen automatisch alle Operatorrechte.

## Nutzung

### Server am Funkgerät (Windows)

1. Auf dem Windows‑Rechner mit angeschlossenem FT‑991A den Steuerungsdienst starten und
   eine Verbindung zum Flask‑Server aufbauen. Der TRX verbindet sich dabei immer automatisch über
  `wss://991a.lima11.de/ws/rig` (anpassbar mit `--server`). Melden Sie sich mit Ihren Benutzerdaten an:
 ```bash
python trx/ft991a_ws_server.py --serial-port COM3 \
    --baudrate 9600 \
    --callsign MYCALL --username MYCALL --password secret \
    --server wss://991a.lima11.de/ws/rig
```
Fehlt eine passende Soundkarte, kann die Audioubertragung mit `--no-audio`
deaktiviert werden:
```bash
python trx/ft991a_ws_server.py --serial-port COM3 \
    --callsign MYCALL --username MYCALL --password secret \
    --no-audio --server wss://991a.lima11.de/ws/rig
```
Bei den Parametern `--server` und `--audio-server` darf auch eine HTTP(S)-Adresse
angegeben werden. Das Programm wandelt diese automatisch in das passende
WebSocket-Schema (`ws://` bzw. `wss://`) um.
Alternativ kann `python trx/trx_gui.py` verwendet werden. Die Oberfläche
speichert Zugangsdaten sowie Audio-, COM-Port- und Baudrate-Auswahl und startet den Dienst nach Klick auf **START**. In einem kleinen Fenster werden dabei nur
die Nutzer angezeigt, die gerade diesen TRX verwenden. Der COM‑Port muss gegebenenfalls angepasst werden. Die Baudrate wird automatisch erkannt, sofern das Funkgerät antwortet. Verbinden sich mehrere Stationen, wählen Sie in der Weboberfläche anhand des Rufzeichens das gewünschte Gerät aus. Jeder TRX muss daher mit einem eindeutigen Rufzeichen angemeldet werden.

### Nutzung als Operator

Die Bedienung eines entfernten TRX erfolgt ausschließlich über die Weboberfläche
des Flask-Servers. Dieser Dienst dient lediglich zur Anbindung des
Funkgeräts selbst und wird daher immer im TRX-Modus betrieben.

### Flask‑Server auf dem Client (Linux)

1. Auf dem Linux‑Rechner die Weboberfläche starten. Der Server nutzt standardmäßig keine serielle Schnittstelle, sondern wartet auf eingehende WebSocket‑Verbindungen des Steuerungsdienstes:
   ```bash
   python flask_server.py
   ```
   Mit dem Parameter `--server` kann optional ein externer Dienst angesprochen werden. Die Anwendung läuft immer auf Port 8084.
   Beim ersten Start existiert lediglich der Benutzer `admin` mit dem Passwort `admin`. Dieses Konto muss sich nach dem Login umbenennen und ein neues Passwort vergeben.
    Weitere Benutzer können sich anschließend selbst registrieren und müssen vom Administrator freigeschaltet werden, bevor sie das Gerät bedienen dürfen.
    Nur Administratoren dürfen neue Benutzer freischalten oder ihnen das Recht zur Nutzung eines TRX erteilen. Administratoren können auch direkt neue Konten anlegen und dabei beliebige Benutzernamen verwenden.
   Über `--list-devices` lassen sich verfügbare Audio‑Geräte anzeigen. Mit
   `--input-device` und `--output-device` kann anschließend die gewünschte
   Geräte‑Nummer gewählt werden.
2. Benutzer registrieren sich über die Weboberfläche mit ihrem Rufzeichen und einem Passwort. Der Benutzername muss einem gültigen deutschen Amateurfunkrufzeichen entsprechen. Erst nach Freischaltung durch einen Administrator dürfen sie das Gerät als Operator bedienen. Bis dahin können sie lediglich im SWL-Modus zuhören.

Die Implementierung bildet nur grundlegende Funktionen ab und kann als Grundlage für eigene Erweiterungen dienen.

## Wichtige CAT-Befehle

| Befehl | Beschreibung |
| ------ | ------------ |
| `FAxxxxxxx;` | VFO-A Frequenz einstellen (lesen mit `FA;`) |
| `MDxx;` | Betriebsart einstellen (lesen mit `MD;`) |
| `TX;` | PTT aktivieren |
| `RX;` | PTT deaktivieren |
| `EU;`/`ED;` | Encoder Up/Down |

Die Weboberfläche nutzt eine PTT-Schaltfläche (oder die Leertaste) zum
Druck‑und‑Sprech-Betrieb. Beim Drücken wird einmal `TX;` gesendet und beim
Loslassen automatisch `RX;`. Eine separate "PTT AUS"-Schaltfläche ist daher
entbehrlich.

## Erstellung von Windows-EXE-Dateien

Um die beiden Programme im Verzeichnis `trx` ohne Python-Installation ausführen zu können, lassen sie sich mit [PyInstaller](https://pyinstaller.org/) in eigenständige EXE-Dateien umwandeln.

1. PyInstaller installieren:
   ```bash
   pip install pyinstaller
   ```
2. Kommandozeilen-Version bauen:
   ```bash
   pyinstaller --onefile trx/ft991a_ws_server.py
   ```
   Die Datei befindet sich danach im Ordner `dist`.
3. GUI-Version ohne Konsolenfenster bauen:
   ```bash
   pyinstaller --onefile --windowed trx/trx_gui.py
   ```
   Auch hier liegt das Ergebnis im Ordner `dist`.
