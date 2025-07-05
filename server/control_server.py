import asyncio
import json
import serial
import websockets

SERIAL_PORT = 'COM3'  # adjust to the serial port of the FT-991A
SERIAL_BAUDRATE = 9600

ser = None
ser_lock = asyncio.Lock()

async def handle_client(websocket, path):
    try:
        async for message in websocket:
            data = json.loads(message)
            cmd = data.get('command')
            async with ser_lock:
                if cmd == 'set_frequency':
                    freq = int(data['frequency'])
                    cat = f'FA{freq:011d};'
                    ser.write(cat.encode('ascii'))
                elif cmd == 'set_mode':
                    mode = int(data['mode'])
                    cat = f'MD{mode:02d};'
                    ser.write(cat.encode('ascii'))
                elif cmd == 'ptt_on':
                    ser.write(b'TX;')
                elif cmd == 'ptt_off':
                    ser.write(b'RX;')
                elif cmd == 'get_frequency':
                    ser.write(b'FA;')
                    resp = ser.readline().decode('ascii').strip()
                    await websocket.send(json.dumps({'frequency': resp}))
    except Exception as e:
        await websocket.send(json.dumps({'error': str(e)}))

async def main():
    global ser
    ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1)
    try:
        async with websockets.serve(handle_client, '0.0.0.0', 9001):
            await asyncio.Future()  # run forever
    finally:
        ser.close()

if __name__ == '__main__':
    asyncio.run(main())
