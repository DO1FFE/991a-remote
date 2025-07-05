# 991a-remote

Dieses Projekt stellt ein einfaches Server-Client-System zum Fernsteuern eines Yaesu FT‑991A 
inklusive Audioübertragung bereit. Sowohl der Server als auch der Client sind in Python implementiert
und lauffähig unter Windows 11 (benötigt Python 3.9 oder neuer).

## Aufbau

- `server/control_server.py` – WebSocket-Server zur Steuerung des Transceivers über die CAT-Schnittstelle.
- `server/audio_bridge.py`  – UDP Audio-Brücke (sendet Audio vom Funkgerät an den Client und umgekehrt).
- `client/control_client.py` – Kommandozeilen-Client zur Steuerung des Geräts.
- `client/audio_client.py`   – Audio-Client zur Sprachübertragung.
- `client/gui_client.py`     – Einfache grafische Oberfläche zur Fernbedienung und Audioübertragung.
- `requirements.txt`         – benötigte Python-Pakete.

## Installation

1. Python installieren (mindestens Version 3.9).
2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```
3. Serielle Schnittstelle des FT‑991A am Server-Rechner ermitteln und in `server/control_server.py` anpassen.

## Nutzung

### Server-Seite

1. `python server/control_server.py` starten, um CAT-Befehle anzunehmen.
2. `python server/audio_bridge.py` starten, um Audio zu übertragen. Vorher `CLIENT_IP` in der Datei auf
die IP des Clients setzen.

### Client-Seite

1. Audioübertragung starten:
   ```bash
   python client/audio_client.py --server <server-ip>
   ```
2. Funkgerät steuern, z. B. Frequenz und Mode setzen:
   ```bash
   python client/control_client.py --server <server-ip> --freq 7100000 --mode 1
   ```
   PTT schalten:
   ```bash
   python client/control_client.py --server <server-ip> --ptt on
   python client/control_client.py --server <server-ip> --ptt off
   ```
Alternativ kann die grafische Oberfläche verwendet werden:
   ```bash
   python client/gui_client.py
   ```

### Erstellung einer Windows-EXE

Die Clients lassen sich mit [PyInstaller](https://www.pyinstaller.org/) zu
eigenständigen EXE-Dateien bundeln. Beispiel:

```bash
pip install pyinstaller
pyinstaller --onefile client/gui_client.py
```

Die erzeugte Datei befindet sich anschließend im Unterordner `dist`.

Die Implementierung ist bewusst einfach gehalten und soll als Ausgangsbasis für eigene Erweiterungen dienen.

