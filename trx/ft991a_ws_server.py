import argparse
import asyncio
import json
import serial
from serial import SerialException
import websockets
import logging
import os

DEFAULT_SERIAL_PORT = 'COM3'
DEFAULT_BAUDRATE = 9600
DEFAULT_WS_PORT = 9001
DEFAULT_CONNECT_URI = 'ws://991a.lima11.de:8084/ws/rig'
DEFAULT_CALLSIGN = 'FT-991A'

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, 'error.log')

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
            async with websockets.connect(uri) as ws:
                await handle_client(ws, announce=handshake, send_updates=True)
        except Exception:
            logger.exception('Connection error, retrying in 5 seconds')
            await asyncio.sleep(5)


async def main():
    global ser
    parser = argparse.ArgumentParser(description='FT-991A control server')
    parser.add_argument('--serial-port', default=DEFAULT_SERIAL_PORT,
                        help='FT-991A serial port')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE,
                        help='Serial baud rate')
    parser.add_argument('--ws-port', type=int, default=DEFAULT_WS_PORT,
                        help='WebSocket port')
    parser.add_argument('--connect', default=DEFAULT_CONNECT_URI,
                        help='Connect to ws://host:port/path instead of serving')
    parser.add_argument('--callsign', default=DEFAULT_CALLSIGN,
                        help='Station callsign to announce')
    parser.add_argument('--username', default=None,
                        help='Username for login')
    parser.add_argument('--password', default=None,
                        help='Password for login')
    parser.add_argument('--mode', choices=['trx', 'operator'], default='trx',
                        help='Login mode')
    args = parser.parse_args()

    global CALLSIGN
    CALLSIGN = args.callsign
    ser = None
    if args.mode == 'trx':
        try:
            ser = serial.Serial(args.serial_port, args.baudrate, timeout=1)
        except SerialException:
            print('Hinweis: Kein TRX verbunden.', flush=True)
            return
    try:
        poll_task = None
        if ser and not args.connect:
            poll_task = asyncio.create_task(poll_trx())
        handshake = {'callsign': CALLSIGN}
        if args.username and args.password:
            handshake.update({'username': args.username,
                              'password': args.password,
                              'mode': args.mode})
        if args.connect:
            await client_loop(args.connect, handshake)
        else:
            async with websockets.serve(
                    lambda ws: handle_client(ws, {'callsign': CALLSIGN}),
                    '0.0.0.0', args.ws_port):
                await asyncio.Future()  # run forever
    finally:
        if poll_task:
            poll_task.cancel()
            await asyncio.gather(poll_task, return_exceptions=True)
        if ser:
            ser.close()

if __name__ == '__main__':
    asyncio.run(main())
