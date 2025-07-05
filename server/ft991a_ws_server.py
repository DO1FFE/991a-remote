import argparse
import asyncio
import json
import serial
import websockets

DEFAULT_SERIAL_PORT = 'COM3'
DEFAULT_BAUDRATE = 9600
DEFAULT_WS_PORT = 9001

ser = None
ser_lock = asyncio.Lock()

async def handle_client(websocket):
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

async def main():
    global ser
    parser = argparse.ArgumentParser(description='FT-991A control server')
    parser.add_argument('--serial-port', default=DEFAULT_SERIAL_PORT,
                        help='FT-991A serial port')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE,
                        help='Serial baud rate')
    parser.add_argument('--ws-port', type=int, default=DEFAULT_WS_PORT,
                        help='WebSocket port')
    args = parser.parse_args()

    ser = serial.Serial(args.serial_port, args.baudrate, timeout=1)
    try:
        async with websockets.serve(handle_client, '0.0.0.0', args.ws_port):
            await asyncio.Future()  # run forever
    finally:
        ser.close()

if __name__ == '__main__':
    asyncio.run(main())
