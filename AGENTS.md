# AGENTS

Dieses Repository enthaelt eine Weboberflaeche zur Fernsteuerung eines Yaesu FT-991A.

## Codeuebersicht
- `flask_server.py`: Hauptanwendung mit Flask.
- `trx/`: WebSocket-Server `ft991a_ws_server.py` und Start-GUI `trx_gui.py`.
- `templates/` und `static/`: HTML- und CSS-Dateien.
- `docs/`: Dokumentation.

## Richtlinien fuer Aenderungen
1. Python 3.9 oder neuer verwenden. Abhaengigkeiten via
   `pip install -r requirements.txt` einrichten.
2. Vor jedem Commit einen Syntaxcheck ausfuehren:
   `python -m py_compile $(git ls-files '*.py')`
3. Commit-Messages:
   - Erste Zeile maximal 72 Zeichen, praegnant im Praesens.
   - Danach optional eine Leerzeile und weitere Details.
4. Bei neuen Skripten oder Funktionen einen kurzen Kommentarblock in Deutsch
   mit Zweck und Nutzung einfuegen.
5. Dokumentation und Kommentare nach Moeglichkeit in Deutsch verfassen.
