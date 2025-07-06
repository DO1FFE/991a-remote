import argparse
import asyncio
import json
import serial
from serial import SerialException
import sys
import websockets

DEFAULT_SERIAL_PORT = 'COM3'
DEFAULT_BAUDRATE = 9600
DEFAULT_WS_PORT = 9001
DEFAULT_CONNECT_URI = 'ws://991a.lima11.de:8084/ws/rig'
DEFAULT_CALLSIGN = 'FT-991A'

ser = None
ser_lock = asyncio.Lock()
CALLSIGN = DEFAULT_CALLSIGN

async def handle_client(websocket, announce=None):
    if announce is not None:
        await websocket.send(json.dumps(announce))
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
                ser.write(b'FA;')
                reply = ser.readline().decode('ascii', errors='ignore').strip()
                await websocket.send(json.dumps({'response': reply}))
            elif cmd == 'get_mode':
                ser.write(b'MD;')
                reply = ser.readline().decode('ascii', errors='ignore').strip()
                await websocket.send(json.dumps({'response': reply}))

async def client_loop(uri, handshake):
    while True:
        try:
            async with websockets.connect(uri) as ws:
                await handle_client(ws, announce=handshake)
        except Exception:
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
        if ser:
            ser.close()

if __name__ == '__main__':
    asyncio.run(main())
