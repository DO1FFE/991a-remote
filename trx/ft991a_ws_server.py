import argparse
import asyncio
import json
import serial
from serial import SerialException
import websockets
from websockets.legacy.client import Connect
import logging
import os
import subprocess
try:
    import pyaudio
except ImportError:  # pragma: no cover
    pyaudio = None

DEFAULT_SERIAL_PORT = 'COM3'
DEFAULT_BAUDRATE = 9600
DEFAULT_CONNECT_URI = 'wss://991a.lima11.de/ws/rig'
DEFAULT_CALLSIGN = 'FT-991A'
DEFAULT_AUDIO_URI = DEFAULT_CONNECT_URI.rsplit('/', 1)[0] + '/rig_audio'
AUDIO_RATE = 16000
AUDIO_FORMAT = pyaudio.paInt16 if pyaudio else 8
CHANNELS = 1
CHUNK = 1024
BAUDRATES = [4800, 9600, 19200, 38400, 57600, 115200]

def _to_ws_url(url):
    """HTTP(S)-URL in WebSocket-URL umwandeln."""
    if url.startswith('http://'):
        return 'ws://' + url[len('http://'):]
    if url.startswith('https://'):
        return 'wss://' + url[len('https://'):]
    return url


class RedirectConnect(Connect):
    """WebSocket-Verbindung, die HTTP-Weiterleitungen interpretiert."""

    def handle_redirect(self, uri: str) -> None:
        super().handle_redirect(_to_ws_url(uri))


def ws_connect(uri: str, **kwargs):
    """Erstelle eine Verbindung mit Unterstuetzung fuer Redirects."""
    return RedirectConnect(_to_ws_url(uri), **kwargs)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(BASE_DIR, 'error.log')


def _get_github_version():
    """Return Git commit count for current revision."""
    try:
        return subprocess.check_output(
            ['git', 'rev-list', '--count', 'HEAD'], cwd=ROOT_DIR
        ).decode().strip()
    except Exception:
        return 'unknown'


GITHUB_VERSION = _get_github_version()
PROGRAM_VERSION = f'FT-991A-Remote V0.1.{GITHUB_VERSION}'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

ser = None
ser_lock = asyncio.Lock()
CALLSIGN = DEFAULT_CALLSIGN
SERIAL_POLLING = 0.2  # seconds
LAST_FREQUENCY = None
LAST_VALUES = {}
MEMORY_CHANNELS = []


class DummySerial:
    """Einfache Simulation eines FT-991A.

    Dieses Dummy-Geraet speichert intern Frequenz, Modus und PTT-Status und
    liefert auf einfache CAT-Befehle plausible Antworten. So kann der
    Websocket-Server auch ohne angeschlossenes Funkgeraet getestet werden.
    """

    def __init__(self):
        self.frequency = 7100000  # 7.100 MHz als Startfrequenz
        self.mode = 1             # LSB
        self.ptt = False
        self._responses = []
        # Einige vordefinierte Speicherkanaele
        self.memories = {
            0: (145500000, 4),  # 145.500 MHz FM
            1: (7100000, 1),    # 7.100 MHz LSB
            2: (144800000, 2),  # 144.800 MHz USB
        }

    def write(self, data):
        """Verarbeite eingehende CAT-Befehle."""
        if isinstance(data, bytes):
            data = data.decode('ascii', errors='ignore')
        for cmd in data.split(';'):
            if not cmd:
                continue
            if cmd.startswith('FA'):
                if len(cmd) == 2:
                    self._responses.append(f'{self.frequency:011d};'.encode('ascii'))
                else:
                    try:
                        self.frequency = int(cmd[2:])
                    except ValueError:
                        pass
            elif cmd.startswith('MD'):
                if len(cmd) == 2:
                    self._responses.append(f'{self.mode:02d};'.encode('ascii'))
                else:
                    try:
                        self.mode = int(cmd[2:])
                    except ValueError:
                        pass
            elif cmd == 'SM':
                self._responses.append(b'0050;')
            elif cmd.startswith('MR'):
                try:
                    idx = int(cmd[2:5])
                except ValueError:
                    idx = None
                if idx is not None and idx in self.memories:
                    freq, mode = self.memories[idx]
                    self._responses.append(
                        f'FA{freq:011d};MD{mode:02d};'.encode('ascii'))
                else:
                    self._responses.append(b'0')  # Speicher leer
            elif cmd.startswith('MC'):
                try:
                    idx = int(cmd[2:5])
                    if idx in self.memories:
                        self.frequency, self.mode = self.memories[idx]
                except ValueError:
                    pass
            elif cmd == 'TX':
                self.ptt = True
            elif cmd == 'RX':
                self.ptt = False
            else:
                # Fuer unbekannte Befehle eine generische OK-Antwort
                self._responses.append(b'')

    def readline(self):
        """Gebe vorbereitete Antwort zurueck."""
        if self._responses:
            return self._responses.pop(0)
        return b''

    def close(self):
        """Kein spezieller Aufraeumvorgang notwendig."""
        pass


def open_serial_autodetect(port, start_baud=DEFAULT_BAUDRATE):
    """Serielle Schnittstelle mit automatischer Baudratenerkennung oeffnen.

    Es wird mit der angegebenen Baudrate begonnen und bei fehlender Antwort auf
    das CAT-Kommando ``FA;`` schrittweise die naechsthoehere Baudrate getestet.
    """

    rates = [b for b in BAUDRATES if b >= start_baud]
    if start_baud not in rates:
        rates.insert(0, start_baud)
    for rate in rates:
        try:
            ser_obj = serial.Serial(port, rate, timeout=1)
        except SerialException:
            continue
        try:
            ser_obj.write(b'FA;')
            if ser_obj.readline().strip():
                logger.info('Baudrate %d erkannt', rate)
                return ser_obj
        except SerialException:
            pass
        ser_obj.close()
    raise SerialException('Baudrate konnte nicht ermittelt werden')


def load_poll_commands():
    """Load CAT commands that allow reading or answering."""
    commands = []
    summary = os.path.join(BASE_DIR, '..', 'docs', 'cat_commands_summary.md')
    try:
        with open(summary, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.startswith('|') or line.startswith('|-'):
                    continue
                parts = [p.strip() for p in line.split('|')]
                if len(parts) < 6 or parts[1] == 'Command':
                    continue
                cmd, read, ans = parts[1], parts[4], parts[5]
                if (read == 'O' or ans == 'O') and len(cmd) == 2:
                    commands.append(f'{cmd};'.encode('ascii'))
    except FileNotFoundError:
        logger.warning('CAT command summary not found, using minimal set')
        commands = [b'FA;', b'MD;', b'SM;']
    return commands


async def read_memory_channels():
    """Read all memory channels once and return list of indices that are used."""
    memories = []
    if ser is None:
        return memories
    try:
        async with ser_lock:
            for i in range(125):
                try:
                    ser.write(f'MR{i:03d};'.encode('ascii'))
                except OSError:
                    # Unter Windows kann PySerial einen OSError liefern, wenn
                    # der Handle ungueltig wurde.
                    logger.warning('Serial write failed during memory scan')
                    break
                try:
                    raw = ser.readline()
                except (AttributeError, TypeError, SerialException):
                    # PySerial wirft mitunter AttributeError, wenn die
                    # Schnittstelle unerwartet geschlossen wurde.
                    logger.warning('Serial read failed during memory scan')
                    break
                reply = raw.decode('ascii', errors='ignore').strip()
                if reply and any(ch != '0' for ch in reply):
                    memories.append(i)
    except Exception:
        logger.exception('Failed to read memories')
    return memories


async def run_startup_tests(send_func=None):
    """Einige einfache CAT-Befehle pruefen und zusaetzlich Speicher testen."""
    if ser is None:
        return {}
    commands = [
        b'FA;',  # Frequenz VFO-A
        b'FB;',  # Frequenz VFO-B
        b'MD;',  # Betriebsart
        b'IF;',  # Statusinformationen
        b'PC;',  # Ausgangsleistung
        b'SM;',  # S-Meter
        b'RG;',  # RF-Gain
        b'GT;',  # AGC-Funktion
        b'NR;',  # Noise Reduction
        b'NB;'   # Noise Blanker
    ]
    results = {}
    memories = []
    try:
        async with ser_lock:
            for cmd in commands:
                try:
                    ser.write(cmd)
                except (OSError, SerialException):
                    logger.warning('Serial write failed during startup tests')
                    break
                try:
                    reply = ser.readline().decode('ascii', errors='ignore').strip()
                except (AttributeError, TypeError, SerialException):
                    logger.warning('Serial read failed during startup tests')
                    break
                key = cmd.decode('ascii').strip(';')
                logger.info('Starttest %s -> %s', key, reply)
                if reply:
                    results[key] = reply
            # Erste zehn Speicherkanaele pruefen
            for i in range(10):
                try:
                    ser.write(f'MR{i:03d};'.encode('ascii'))
                except (OSError, SerialException):
                    logger.warning('Serial write failed during memory scan')
                    break
                try:
                    reply = ser.readline().decode('ascii', errors='ignore').strip()
                except (AttributeError, TypeError, SerialException):
                    logger.warning('Serial read failed during memory scan')
                    break
                logger.info('Starttest MR%03d -> %s', i, reply)
                if reply and any(ch != '0' for ch in reply):
                    memories.append(i)
    except Exception:
        logger.exception('Starttests fehlgeschlagen')
    if send_func is not None:
        if results:
            try:
                await send_func({'values': results})
            except Exception:
                logger.exception('Senden der Starttests fehlgeschlagen')
        if memories:
            try:
                await send_func({'memory_channels': memories})
            except Exception:
                logger.exception('Senden der Speicherliste fehlgeschlagen')
    return results


POLL_COMMANDS = load_poll_commands()

async def poll_trx(send_func=None):
    """Poll the transceiver for various CAT values and optionally send updates."""
    global LAST_FREQUENCY, LAST_VALUES
    while True:
        await asyncio.sleep(SERIAL_POLLING)
        if ser is None:
            continue
        changed = {}
        try:
            async with ser_lock:
                for cmd in POLL_COMMANDS:
                    ser.write(cmd)
                    reply = ser.readline().decode('ascii', errors='ignore').strip()
                    if not reply:
                        continue
                    key = cmd.decode('ascii').strip(';')
                    if LAST_VALUES.get(key) != reply:
                        LAST_VALUES[key] = reply
                        changed[key] = reply
                    if cmd == b'FA;':
                        LAST_FREQUENCY = reply
        except Exception:
            logger.exception('Polling error')
        if changed and send_func is not None:
            try:
                await send_func(changed)
            except Exception:
                logger.exception('Failed to send update')

async def handle_client(websocket, announce=None, send_updates=False):
    if announce is not None:
        await websocket.send(json.dumps(announce))
    if ser:
        await run_startup_tests(lambda data: websocket.send(json.dumps(data)))
        memories = await read_memory_channels()
        if memories:
            await websocket.send(json.dumps({'memory_channels': memories}))
    poll_task = None
    ping_task = None
    if ser and send_updates:
        poll_task = asyncio.create_task(
            poll_trx(lambda vals: websocket.send(json.dumps({'values': vals}))))
    async def ping_loop():
        while True:
            try:
                start = asyncio.get_event_loop().time()
                pong = await websocket.ping()
                await pong
                rtt = int((asyncio.get_event_loop().time() - start) * 1000)
                await websocket.send(json.dumps({'values': {'RTT': rtt}}))
            except Exception:
                logger.exception('Ping failed')
                break
            await asyncio.sleep(5)
    ping_task = asyncio.create_task(ping_loop())
    try:
        async for message in websocket:
            data = json.loads(message)
            cmd = data.get('command')
            async with ser_lock:
                if cmd == 'set_frequency':
                    try:
                        freq = int(data['frequency'])
                        ser.write(f'FA{freq:011d};'.encode('ascii'))
                    except (KeyError, ValueError):
                        pass
                elif cmd == 'set_mode':
                    try:
                        mode = int(data['mode'])
                        ser.write(f'MD{mode:02d};'.encode('ascii'))
                    except (KeyError, ValueError):
                        pass
                elif cmd == 'ptt_on':
                    ser.write(b'TX;')
                elif cmd == 'ptt_off':
                    ser.write(b'RX;')
                elif cmd == 'cat':
                    value = data.get('data', '')
                    if not value.endswith(';'):
                        value += ';'
                    ser.write(value.encode('ascii'))
                elif cmd == 'get_frequency':
                    reply = LAST_VALUES.get('FA', LAST_FREQUENCY)
                    if reply is None:
                        ser.write(b'FA;')
                        reply = ser.readline().decode('ascii', errors='ignore').strip()
                    await websocket.send(json.dumps({'response': reply}))
                elif cmd == 'get_mode':
                    reply = LAST_VALUES.get('MD')
                    if reply is None:
                        ser.write(b'MD;')
                        reply = ser.readline().decode('ascii', errors='ignore').strip()
                    await websocket.send(json.dumps({'response': reply}))
                elif cmd == 'get_smeter':
                    reply = LAST_VALUES.get('SM')
                    if reply is None:
                        ser.write(b'SM;')
                        reply = ser.readline().decode('ascii', errors='ignore').strip()
                    await websocket.send(json.dumps({'response': reply}))
    finally:
        if poll_task:
            poll_task.cancel()
            await asyncio.gather(poll_task, return_exceptions=True)
        if ping_task:
            ping_task.cancel()
            await asyncio.gather(ping_task, return_exceptions=True)

async def client_loop(uri, handshake):
    while True:
        try:
            async with ws_connect(uri) as ws:
                await handle_client(ws, announce=handshake, send_updates=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('Connection error (%s), retrying in 1 second', exc)
            await asyncio.sleep(1)


async def audio_loop(uri, handshake, input_dev=None, output_dev=None):
    if pyaudio is None:
        logger.error('pyaudio not installed, audio disabled')
        return
    p = pyaudio.PyAudio()
    in_stream = p.open(format=AUDIO_FORMAT, channels=CHANNELS, rate=AUDIO_RATE,
                       input=True, frames_per_buffer=CHUNK,
                       input_device_index=input_dev)
    out_stream = p.open(format=AUDIO_FORMAT, channels=CHANNELS, rate=AUDIO_RATE,
                        output=True, frames_per_buffer=CHUNK,
                        output_device_index=output_dev)
    while True:
        try:
            async with ws_connect(uri) as ws:
                await ws.send(json.dumps(handshake))

                async def sender():
                    while True:
                        data = in_stream.read(CHUNK, exception_on_overflow=False)
                        await ws.send(data)

                async def receiver():
                    async for msg in ws:
                        out_stream.write(msg)

                await asyncio.gather(sender(), receiver())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning('Audio connection error (%s), retrying in 1 second', exc)
            await asyncio.sleep(1)


async def main():
    global ser
    parser = argparse.ArgumentParser(description='FT-991A control server')
    parser.add_argument('--serial-port', default=DEFAULT_SERIAL_PORT,
                        help='FT-991A serial port')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE,
                        help='Serial baud rate')
    parser.add_argument('--callsign', default=DEFAULT_CALLSIGN,
                        help='Station callsign to announce')
    parser.add_argument('--server', default=DEFAULT_CONNECT_URI,
                        help='Flask server ws(s)://host:port/ws/rig')
    parser.add_argument('--audio-server', default=DEFAULT_AUDIO_URI,
                        help='Audio server ws(s)://host:port/ws/rig_audio')
    parser.add_argument('--input-device', type=int, default=None,
                        help='Audio input device index')
    parser.add_argument('--output-device', type=int, default=None,
                        help='Audio output device index')
    parser.add_argument('--username', default=None,
                        help='Username for login')
    parser.add_argument('--password', default=None,
                        help='Password for login')
    args = parser.parse_args()

    global CALLSIGN
    CALLSIGN = args.callsign
    ser = None
    try:
        ser = open_serial_autodetect(args.serial_port, args.baudrate)
    except SerialException:
        print('Hinweis: Kein TRX gefunden, Dummy wird verwendet.', flush=True)
        ser = DummySerial()
    try:
        handshake = {'callsign': CALLSIGN}
        if args.username and args.password:
            handshake.update({'username': args.username,
                              'password': args.password,
                              'mode': 'trx'})
        audio_handshake = None
        if args.username and args.password:
            audio_handshake = {'callsign': CALLSIGN,
                               'username': args.username,
                               'password': args.password,
                               'mode': 'trx_audio'}
        tasks = [client_loop(args.server, handshake)]
        if audio_handshake:
            tasks.append(audio_loop(args.audio_server, audio_handshake,
                                   args.input_device, args.output_device))
        await asyncio.gather(*tasks)
    finally:
        if ser:
            ser.close()

if __name__ == '__main__':
    asyncio.run(main())
