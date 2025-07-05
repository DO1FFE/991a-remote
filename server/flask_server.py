import argparse
import threading
import serial
import asyncio
import json
import websockets
from flask import Flask, render_template, request, redirect, session, url_for
from flask_sock import Sock
import pyaudio

DEFAULT_SERIAL_PORT = 'COM3'
DEFAULT_BAUDRATE = 9600
DEFAULT_USERNAME = 'admin'
DEFAULT_PASSWORD = 'secret'
DEFAULT_REMOTE_SERVER = 'ws://991a.lima11.de:9001'

SERIAL_PORT = DEFAULT_SERIAL_PORT
SERIAL_BAUDRATE = DEFAULT_BAUDRATE
USERNAME = DEFAULT_USERNAME
PASSWORD = DEFAULT_PASSWORD
REMOTE_SERVER = None
AUDIO_RATE = 16000
AUDIO_FORMAT = pyaudio.paInt16
CHANNELS = 1
CHUNK = 1024
INPUT_DEVICE_INDEX = None
OUTPUT_DEVICE_INDEX = None
RIG_WS = None
RIG_LOCK = threading.Lock()

app = Flask(__name__)
DEFAULT_SECRET = 'change-me'
app.secret_key = DEFAULT_SECRET

sock = Sock(app)

ser = None

@sock.route('/ws/rig')
def rig(ws):
    global RIG_WS
    RIG_WS = ws
    try:
        while True:
            msg = ws.receive()
            if msg is None:
                break
    finally:
        if RIG_WS is ws:
            RIG_WS = None

@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == USERNAME and request.form.get('password') == PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        return render_template('login.html', error='Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/command', methods=['POST'])
def command():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    cmd = request.form.get('cmd')
    value = request.form.get('value', '')
    if REMOTE_SERVER:
        data = {'command': None}
        if cmd == 'frequency':
            try:
                freq = int(value)
                data = {'command': 'set_frequency', 'frequency': freq}
            except ValueError:
                return ('', 204)
        elif cmd == 'mode':
            try:
                mode = int(value)
                data = {'command': 'set_mode', 'mode': mode}
            except ValueError:
                return ('', 204)
        elif cmd == 'ptt_on':
            data = {'command': 'ptt_on'}
        elif cmd == 'ptt_off':
            data = {'command': 'ptt_off'}
        elif cmd == 'shift':
            if value in ('0', '1', '2'):
                data = {'command': 'cat', 'data': f'RT{value};'}
            else:
                return ('', 204)
        elif cmd == 'offset':
            try:
                off = int(value)
                data = {'command': 'cat', 'data': f'OF{off:07d};'}
            except ValueError:
                return ('', 204)
        elif cmd == 'ctcss':
            try:
                tone = float(value)
                data = {'command': 'cat', 'data': f'CT{int(tone*10):04d};'}
            except ValueError:
                return ('', 204)
        elif cmd == 'dcs':
            try:
                code = int(value)
                data = {'command': 'cat', 'data': f'DS{code:03d};'}
            except ValueError:
                return ('', 204)
        elif cmd == 'mic_gain':
            try:
                gain = int(value)
                data = {'command': 'cat', 'data': f'MG{gain:03d};'}
            except ValueError:
                return ('', 204)
        elif cmd == 'cat':
            if not value.endswith(';'):
                value += ';'
            data = {'command': 'cat', 'data': value}
        elif cmd == 'get_frequency':
            data = {'command': 'get_frequency'}
        elif cmd == 'get_mode':
            data = {'command': 'get_mode'}
        else:
            return ('', 204)

        async def send():
            async with websockets.connect(REMOTE_SERVER) as ws:
                await ws.send(json.dumps(data))
                if cmd in ('get_frequency', 'get_mode'):
                    return await ws.recv()
            return None
        resp = asyncio.run(send())
        if resp is not None:
            return resp
    elif RIG_WS:
        data = {'command': None}
        if cmd == 'frequency':
            try:
                freq = int(value)
                data = {'command': 'set_frequency', 'frequency': freq}
            except ValueError:
                return ('', 204)
        elif cmd == 'mode':
            try:
                mode = int(value)
                data = {'command': 'set_mode', 'mode': mode}
            except ValueError:
                return ('', 204)
        elif cmd == 'ptt_on':
            data = {'command': 'ptt_on'}
        elif cmd == 'ptt_off':
            data = {'command': 'ptt_off'}
        elif cmd == 'shift':
            if value in ('0', '1', '2'):
                data = {'command': 'cat', 'data': f'RT{value};'}
            else:
                return ('', 204)
        elif cmd == 'offset':
            try:
                off = int(value)
                data = {'command': 'cat', 'data': f'OF{off:07d};'}
            except ValueError:
                return ('', 204)
        elif cmd == 'ctcss':
            try:
                tone = float(value)
                data = {'command': 'cat', 'data': f'CT{int(tone*10):04d};'}
            except ValueError:
                return ('', 204)
        elif cmd == 'dcs':
            try:
                code = int(value)
                data = {'command': 'cat', 'data': f'DS{code:03d};'}
            except ValueError:
                return ('', 204)
        elif cmd == 'mic_gain':
            try:
                gain = int(value)
                data = {'command': 'cat', 'data': f'MG{gain:03d};'}
            except ValueError:
                return ('', 204)
        elif cmd == 'cat':
            if not value.endswith(';'):
                value += ';'
            data = {'command': 'cat', 'data': value}
        elif cmd == 'get_frequency':
            data = {'command': 'get_frequency'}
        elif cmd == 'get_mode':
            data = {'command': 'get_mode'}
        else:
            return ('', 204)

        with RIG_LOCK:
            RIG_WS.send(json.dumps(data))
            if cmd in ('get_frequency', 'get_mode'):
                resp = RIG_WS.receive()
                if resp:
                    return resp
    else:
        if cmd == 'frequency':
            try:
                freq = int(value)
                ser.write(f'FA{freq:011d};'.encode('ascii'))
            except ValueError:
                pass
        elif cmd == 'mode':
            try:
                mode = int(value)
                ser.write(f'MD{mode:02d};'.encode('ascii'))
            except ValueError:
                pass
        elif cmd == 'ptt_on':
            ser.write(b'TX;')
        elif cmd == 'ptt_off':
            ser.write(b'RX;')
        elif cmd == 'shift':
            if value in ('0', '1', '2'):
                ser.write(f'RT{value};'.encode('ascii'))
            else:
                pass
        elif cmd == 'offset':
            try:
                off = int(value)
                ser.write(f'OF{off:07d};'.encode('ascii'))
            except ValueError:
                pass
        elif cmd == 'ctcss':
            try:
                tone = float(value)
                ser.write(f'CT{int(tone*10):04d};'.encode('ascii'))
            except ValueError:
                pass
        elif cmd == 'dcs':
            try:
                code = int(value)
                ser.write(f'DS{code:03d};'.encode('ascii'))
            except ValueError:
                pass
        elif cmd == 'mic_gain':
            try:
                gain = int(value)
                ser.write(f'MG{gain:03d};'.encode('ascii'))
            except ValueError:
                pass
        elif cmd == 'cat':
            if not value.endswith(';'):
                value += ';'
            ser.write(value.encode('ascii'))
        elif cmd == 'get_frequency':
            ser.write(b'FA;')
            ser.readline()
        elif cmd == 'get_mode':
            ser.write(b'MD;')
            ser.readline()
    return ('', 204)

@sock.route('/ws/audio')
def audio(ws):
    p = pyaudio.PyAudio()
    input_stream = p.open(format=AUDIO_FORMAT, channels=CHANNELS, rate=AUDIO_RATE,
                          input=True, frames_per_buffer=CHUNK,
                          input_device_index=INPUT_DEVICE_INDEX)
    output_stream = p.open(format=AUDIO_FORMAT, channels=CHANNELS, rate=AUDIO_RATE,
                           output=True, frames_per_buffer=CHUNK,
                           output_device_index=OUTPUT_DEVICE_INDEX)
    running = True

    def send_audio():
        while running:
            data = input_stream.read(CHUNK, exception_on_overflow=False)
            try:
                ws.send(data)
            except Exception:
                break

    t = threading.Thread(target=send_audio, daemon=True)
    t.start()
    try:
        while True:
            msg = ws.receive()
            if msg is None:
                break
            output_stream.write(msg)
    except Exception:
        pass
    finally:
        running = False
        input_stream.close()
        output_stream.close()
        p.terminate()

def main():
    global SERIAL_PORT, SERIAL_BAUDRATE, USERNAME, PASSWORD, ser, REMOTE_SERVER
    parser = argparse.ArgumentParser(description='FT-991A remote server')
    parser.add_argument('--serial-port', default=DEFAULT_SERIAL_PORT,
                        help='FT-991A serial port')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE,
                        help='Serial baud rate')
    parser.add_argument('--server', default=DEFAULT_REMOTE_SERVER,
                        help='Remote control server ws://host:port')
    parser.add_argument('--username', default=DEFAULT_USERNAME,
                        help='Login username')
    parser.add_argument('--password', default=DEFAULT_PASSWORD,
                        help='Login password')
    parser.add_argument('--http-port', type=int, default=8000,
                        help='Port for the web interface')
    parser.add_argument('--secret', default=DEFAULT_SECRET,
                        help='Flask secret key')
    parser.add_argument('--input-device', type=int, default=None,
                        help='Audio input device index')
    parser.add_argument('--output-device', type=int, default=None,
                        help='Audio output device index')
    parser.add_argument('--list-devices', action='store_true',
                        help='List audio devices and exit')
    args = parser.parse_args()

    SERIAL_PORT = args.serial_port
    SERIAL_BAUDRATE = args.baudrate
    USERNAME = args.username
    PASSWORD = args.password
    app.secret_key = args.secret
    global INPUT_DEVICE_INDEX, OUTPUT_DEVICE_INDEX
    INPUT_DEVICE_INDEX = args.input_device
    OUTPUT_DEVICE_INDEX = args.output_device

    if args.list_devices:
        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            print(f"{i}: {info['name']}")
        p.terminate()
        return

    REMOTE_SERVER = args.server
    if REMOTE_SERVER:
        ser = None
    else:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUDRATE, timeout=1)
    try:
        app.run(host='0.0.0.0', port=args.http_port)
    finally:
        if ser:
            ser.close()


if __name__ == '__main__':
    main()
