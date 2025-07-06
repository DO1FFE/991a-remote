import argparse
import threading
import serial
import asyncio
import json
import os
import websockets
from flask import Flask, render_template, request, redirect, session, url_for
import datetime
from flask_sock import Sock
from werkzeug.security import generate_password_hash, check_password_hash
import pyaudio

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_SERIAL_PORT = 'COM3'
DEFAULT_BAUDRATE = 9600
DEFAULT_REMOTE_SERVER = 'ws://991a.lima11.de:9001'

USERS_FILE = os.path.join(BASE_DIR, 'users.json')
USERS = {}
USERS_LOCK = threading.Lock()

SERIAL_PORT = DEFAULT_SERIAL_PORT
SERIAL_BAUDRATE = DEFAULT_BAUDRATE
REMOTE_SERVER = None
AUDIO_RATE = 16000
AUDIO_FORMAT = pyaudio.paInt16
CHANNELS = 1
CHUNK = 1024
INPUT_DEVICE_INDEX = None
OUTPUT_DEVICE_INDEX = None
RIGS = {}
RIG_LOCK = threading.Lock()
OPERATORS = {}
OPERATOR_LOCK = threading.Lock()

TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
app = Flask(__name__, template_folder=TEMPLATES_DIR,
            static_folder=STATIC_DIR)
DEFAULT_SECRET = 'change-me'
app.secret_key = DEFAULT_SECRET
CURRENT_YEAR = datetime.datetime.now().year

sock = Sock(app)

ser = None


def load_users():
    global USERS
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            USERS = json.load(f)
        for u in USERS.values():
            if 'trx' not in u:
                u['trx'] = False
    else:
        USERS = {
            'admin': {
                'password': generate_password_hash('admin'),
                'role': 'admin',
                'approved': True,
                'needs_change': True,
                'trx': False,
            }
        }
        save_users()


def save_users():
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(USERS, f)


load_users()

@sock.route('/ws/rig')
def rig(ws):
    first = ws.receive()
    callsign = None
    username = None
    password = None
    mode = 'trx'
    try:
        data = json.loads(first)
        callsign = data.get('callsign')
        username = data.get('username')
        password = data.get('password')
        mode = data.get('mode', 'trx')
    except Exception:
        ws.close()
        return
    if not username or not password:
        ws.close()
        return
    with USERS_LOCK:
        user = USERS.get(username)
    if not user or not check_password_hash(user['password'], password):
        ws.close()
        return
    if mode == 'trx' and not user.get('trx'):
        ws.close()
        return
    if not callsign:
        callsign = username if mode == 'trx' else f'op_{username}'

    if mode == 'trx':
        with RIG_LOCK:
            RIGS[callsign] = ws
    try:
        while True:
            msg = ws.receive()
            if msg is None:
                break
    finally:
        if mode == 'trx':
            with RIG_LOCK:
                if RIGS.get(callsign) is ws:
                    del RIGS[callsign]

@app.route('/')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    with RIG_LOCK:
        rigs = list(RIGS.keys())
    selected = session.get('rig')
    if selected not in rigs and rigs:
        selected = rigs[0]
        session['rig'] = selected
    user = session.get('user')
    role = session.get('role')
    approved = session.get('approved')
    with OPERATOR_LOCK:
        operator = OPERATORS.get(selected)
    operator_status = None
    if operator:
        with USERS_LOCK:
            op_data = USERS.get(operator)
        if op_data:
            if op_data.get('role') == 'admin' or op_data.get('approved'):
                operator_status = 'Operator'
            else:
                operator_status = 'SWL'
    return render_template(
        'index.html', rigs=rigs, selected_rig=selected,
        operator=operator, operator_status=operator_status,
        user=user, role=role,
        approved=approved, year=CURRENT_YEAR)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        user = USERS.get(username)
        if user and check_password_hash(user['password'], password):
            session['logged_in'] = True
            session['user'] = username
            session['role'] = user.get('role', 'operator')
            session['approved'] = user.get('approved', False) or session['role'] == 'admin'
            if user.get('needs_change'):
                return redirect(url_for('change_credentials'))
            return redirect(url_for('index'))
        return render_template('login.html', error='Invalid credentials', year=CURRENT_YEAR)
    return render_template('login.html', year=CURRENT_YEAR)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username or not password:
            return render_template('register.html', error='Invalid data', year=CURRENT_YEAR)
        with USERS_LOCK:
            if username in USERS:
                return render_template('register.html', error='User exists', year=CURRENT_YEAR)
            USERS[username] = {
                'password': generate_password_hash(password),
                'role': 'operator',
                'approved': False,
                'needs_change': False,
                'trx': False,
            }
            save_users()
        return render_template('login.html', message='Registration successful. Await approval.', year=CURRENT_YEAR)
    return render_template('register.html', year=CURRENT_YEAR)


@app.route('/change_credentials', methods=['GET', 'POST'])
def change_credentials():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    username = session.get('user')
    user = USERS.get(username)
    if not user:
        return redirect(url_for('logout'))
    if request.method == 'POST':
        new_username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not new_username or not password:
            return render_template('change_credentials.html', error='Invalid data', year=CURRENT_YEAR)
        with USERS_LOCK:
            if new_username != username and new_username in USERS:
                return render_template('change_credentials.html', error='User exists', year=CURRENT_YEAR)
            user['password'] = generate_password_hash(password)
            user['needs_change'] = False
            if new_username != username:
                USERS[new_username] = user
                del USERS[username]
                session['user'] = new_username
        save_users()
        return redirect(url_for('index'))
    role = session.get('role')
    return render_template('change_credentials.html', current=username, year=CURRENT_YEAR, role=role)


@app.route('/admin/users', methods=['GET', 'POST'])
def admin_users():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        action = request.form.get('action')
        with USERS_LOCK:
            user = USERS.get(username)
            if user:
                if action == 'approve':
                    user['approved'] = True
                elif action == 'make_admin':
                    user['role'] = 'admin'
                    user['approved'] = True
                elif action == 'make_trx':
                    user['trx'] = True
                elif action == 'remove_trx':
                    user['trx'] = False
                save_users()
    role = session.get('role')
    return render_template('userlist.html', users=USERS, year=CURRENT_YEAR, role=role)


@app.route('/admin/user/<username>', methods=['GET', 'POST'])
def admin_edit_user(username):
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    with USERS_LOCK:
        user = USERS.get(username)
    if not user:
        return redirect(url_for('admin_users'))
    error = None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'delete':
            with USERS_LOCK:
                USERS.pop(username, None)
                save_users()
            return redirect(url_for('admin_users'))
        new_username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        role_val = request.form.get('role') or user.get('role', 'operator')
        approved = request.form.get('approved') == '1'
        trx = request.form.get('trx') == '1'
        with USERS_LOCK:
            if new_username != username and new_username in USERS:
                error = 'User exists'
            else:
                if new_username != username:
                    USERS[new_username] = USERS.pop(username)
                    username = new_username
                if password:
                    USERS[username]['password'] = generate_password_hash(password)
                    USERS[username]['needs_change'] = False
                USERS[username]['role'] = role_val
                USERS[username]['approved'] = approved
                USERS[username]['trx'] = trx
                save_users()
                return redirect(url_for('admin_users'))
    role = session.get('role')
    return render_template('edit_user.html', user_data=user, username=username, year=CURRENT_YEAR, role=role, error=error)

@app.route('/logout')
def logout():
    user = session.pop('user', None)
    rig = session.get('rig')
    if user and rig:
        with OPERATOR_LOCK:
            if OPERATORS.get(rig) == user:
                OPERATORS.pop(rig, None)
    session.pop('logged_in', None)
    session.pop('role', None)
    session.pop('approved', None)
    return redirect(url_for('login'))

@app.route('/select_rig', methods=['POST'])
def select_rig():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    rig = request.form.get('rig')
    with RIG_LOCK:
        if rig in RIGS:
            session['rig'] = rig
    return redirect(url_for('index'))

@app.route('/take_control', methods=['POST'])
def take_control():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if not session.get('approved') and session.get('role') != 'admin':
        return redirect(url_for('index'))
    rig = session.get('rig')
    user = session.get('user')
    if rig and user:
        with OPERATOR_LOCK:
            if OPERATORS.get(rig) in (None, user):
                OPERATORS[rig] = user
    return redirect(url_for('index'))

@app.route('/release_control', methods=['POST'])
def release_control():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if not session.get('approved') and session.get('role') != 'admin':
        return redirect(url_for('index'))
    rig = session.get('rig')
    user = session.get('user')
    if rig and user:
        with OPERATOR_LOCK:
            if OPERATORS.get(rig) == user:
                OPERATORS.pop(rig, None)
    return redirect(url_for('index'))

@app.route('/command', methods=['POST'])
def command():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if not session.get('approved') and session.get('role') != 'admin':
        return ('', 403)
    user = session.get('user')
    rig = session.get('rig')
    if rig:
        with OPERATOR_LOCK:
            if OPERATORS.get(rig) != user:
                return ('', 403)
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
    elif RIGS:
        rig = session.get('rig')
        with RIG_LOCK:
            ws = RIGS.get(rig)
        if not ws:
            return ('', 204)
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
            ws.send(json.dumps(data))
            if cmd in ('get_frequency', 'get_mode'):
                resp = ws.receive()
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
    global SERIAL_PORT, SERIAL_BAUDRATE, ser, REMOTE_SERVER
    parser = argparse.ArgumentParser(description='FT-991A remote server')
    parser.add_argument('--serial-port', default=DEFAULT_SERIAL_PORT,
                        help='FT-991A serial port')
    parser.add_argument('--baudrate', type=int, default=DEFAULT_BAUDRATE,
                        help='Serial baud rate')
    parser.add_argument('--server', default=DEFAULT_REMOTE_SERVER,
                        help='Remote control server ws://host:port')
    parser.add_argument('--http-port', type=int, default=8084,
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
