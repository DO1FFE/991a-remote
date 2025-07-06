import argparse
import threading
import asyncio
import json
import os
import re
import websockets
import logging
from flask import Flask, render_template, request, redirect, session, url_for, jsonify
import datetime
import time
from flask_sock import Sock
from werkzeug.security import generate_password_hash, check_password_hash
try:
    import pyaudio
except ImportError:  # pragma: no cover - optional dependency
    pyaudio = None

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

DEFAULT_REMOTE_SERVER = None

USERS_FILE = os.path.join(BASE_DIR, 'users.json')
USERS = {}
USERS_LOCK = threading.Lock()

REMOTE_SERVER = None
AUDIO_RATE = 16000
AUDIO_FORMAT = pyaudio.paInt16 if pyaudio else 8  # 8 == paInt16
CHANNELS = 1
CHUNK = 1024
INPUT_DEVICE_INDEX = None
OUTPUT_DEVICE_INDEX = None
RIGS = {}
RIG_LOCK = threading.Lock()
OPERATORS = {}
OPERATOR_LOCK = threading.Lock()
RIG_VALUES = {}
VALUES_LOCK = threading.Lock()
RIG_MEMORIES = {}
MEMORY_LOCK = threading.Lock()
STATUS_CLIENTS = set()
STATUS_LOCK = threading.Lock()
ACTIVE_USERS = {}
ACTIVE_LOCK = threading.Lock()
USER_RTT = {}
ACTIVE_WS_CLIENTS = set()
ACTIVE_WS_LOCK = threading.Lock()
USER_RIG = {}
USER_RIG_LOCK = threading.Lock()
RIG_AUDIO = {}
RIG_AUDIO_LOCK = threading.Lock()
AUDIO_CLIENTS = {}
AUDIO_CLIENTS_LOCK = threading.Lock()

GERMAN_PREFIXES = (
    'DA', 'DB', 'DC', 'DD', 'DF', 'DG', 'DH', 'DJ',
    'DK', 'DL', 'DM', 'DN', 'DO', 'DP', 'DQ', 'DR'
)
CALLSIGN_RE = re.compile(r'^(?:' + '|'.join(GERMAN_PREFIXES) + r')[0-9][A-Z]{1,3}$', re.IGNORECASE)


def is_valid_callsign(callsign):
    """Return True if callsign matches German prefix pattern."""
    return bool(CALLSIGN_RE.match(callsign))

TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')
STATIC_DIR = os.path.join(BASE_DIR, 'static')
app = Flask(__name__, template_folder=TEMPLATES_DIR,
            static_folder=STATIC_DIR)
DEFAULT_SECRET = 'change-me'
app.secret_key = DEFAULT_SECRET
CURRENT_YEAR = datetime.datetime.now().year

sock = Sock(app)


def load_answer_commands():
    """Return list of CAT commands that provide an answer."""
    summary = os.path.join(BASE_DIR, 'docs', 'cat_commands_summary.md')
    commands = []
    try:
        with open(summary, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.startswith('|') or line.startswith('|-'):
                    continue
                parts = [p.strip() for p in line.split('|')]
                if len(parts) < 6 or parts[1] == 'Command':
                    continue
                cmd, ans = parts[1], parts[5]
                if ans == 'O' and len(cmd) == 2:
                    commands.append(f'{cmd};')
    except FileNotFoundError:
        pass
    return commands


def save_answers(data):
    answers_file = os.path.join(BASE_DIR, 'docs', 'cat_answers.json')
    try:
        with open(answers_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        logger.exception('Failed to save answers')


def load_saved_answers():
    answers_file = os.path.join(BASE_DIR, 'docs', 'cat_answers.json')
    try:
        with open(answers_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def fetch_cat_answers():
    """Collect answers for CAT commands and return dict."""
    commands = load_answer_commands()
    results = {}
    if REMOTE_SERVER:
        async def run():
            res = {}
            try:
                async with websockets.connect(REMOTE_SERVER) as ws:
                    for cmd in commands:
                        await ws.send(json.dumps({'command': 'cat', 'data': cmd}))
                        try:
                            reply = await ws.recv()
                        except Exception:
                            reply = ''
                        res[cmd.strip(';')] = reply
            except Exception:
                logger.exception('Failed to fetch answers')
            return res
        results = asyncio.run(run())
    elif RIGS:
        rig = session.get('rig')
        with RIG_LOCK:
            ws = RIGS.get(rig)
        if ws:
            for cmd in commands:
                ws.send(json.dumps({'command': 'cat', 'data': cmd}))
                try:
                    reply = ws.receive()
                except Exception:
                    reply = ''
                results[cmd.strip(';')] = reply
    return results


def broadcast(update):
    data = json.dumps(update)
    remove = []
    with STATUS_LOCK:
        for ws in list(STATUS_CLIENTS):
            try:
                ws.send(data)
            except Exception:
                remove.append(ws)
        for ws in remove:
            STATUS_CLIENTS.discard(ws)


def broadcast_active_users():
    now = time.time()
    with ACTIVE_LOCK:
        users = []
        for u, ts in list(ACTIVE_USERS.items()):
            if now - ts < 10:
                with USER_RIG_LOCK:
                    users.append((u, USER_RTT.get(u), USER_RIG.get(u)))
            else:
                del ACTIVE_USERS[u]
                USER_RTT.pop(u, None)
    data = json.dumps({'active_users': users})
    remove = []
    with ACTIVE_WS_LOCK:
        for ws in list(ACTIVE_WS_CLIENTS):
            try:
                ws.send(data)
            except Exception:
                remove.append(ws)
        for ws in remove:
            ACTIVE_WS_CLIENTS.discard(ws)


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
        logger.exception('Invalid handshake received')
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
            if mode == 'trx':
                try:
                    data = json.loads(msg)
                except Exception:
                    continue
                values = data.get('values')
                if values:
                    with VALUES_LOCK:
                        cur = RIG_VALUES.setdefault(callsign, {})
                        cur.update(values)
                    broadcast({'rig': callsign, 'values': values})
                memories = data.get('memory_channels')
                if memories is not None:
                    with MEMORY_LOCK:
                        RIG_MEMORIES[callsign] = memories
                    broadcast({'rig': callsign, 'memories': memories})
    finally:
        if mode == 'trx':
            with RIG_LOCK:
                if RIGS.get(callsign) is ws:
                    del RIGS[callsign]
            with VALUES_LOCK:
                RIG_VALUES.pop(callsign, None)
            with MEMORY_LOCK:
                RIG_MEMORIES.pop(callsign, None)


@sock.route('/ws/rig_audio')
def rig_audio(ws):
    """Audio connection from a transceiver service."""
    first = ws.receive()
    try:
        data = json.loads(first)
        callsign = data.get('callsign')
        username = data.get('username')
        password = data.get('password')
    except Exception:
        ws.close()
        return
    if not username or not password:
        ws.close()
        return
    with USERS_LOCK:
        user = USERS.get(username)
    if not user or not check_password_hash(user['password'], password) or not user.get('trx'):
        ws.close()
        return
    if not callsign:
        callsign = username
    with RIG_AUDIO_LOCK:
        RIG_AUDIO[callsign] = ws
    try:
        while True:
            msg = ws.receive()
            if msg is None:
                break
            remove = []
            with AUDIO_CLIENTS_LOCK:
                clients = list(AUDIO_CLIENTS.get(callsign, set()))
            for c in clients:
                try:
                    c.send(msg)
                except Exception:
                    remove.append(c)
            if remove:
                with AUDIO_CLIENTS_LOCK:
                    for c in remove:
                        AUDIO_CLIENTS.get(callsign, set()).discard(c)
    finally:
        with RIG_AUDIO_LOCK:
            if RIG_AUDIO.get(callsign) is ws:
                del RIG_AUDIO[callsign]

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
    if user:
        with USER_RIG_LOCK:
            USER_RIG[user] = selected
    role = session.get('role')
    approved = session.get('approved')
    unapproved_count = 0
    if role == 'admin':
        with USERS_LOCK:
            unapproved_count = sum(1 for u in USERS.values() if not u.get('approved'))
    with OPERATOR_LOCK:
        operator = OPERATORS.get(selected)
    with MEMORY_LOCK:
        memories = RIG_MEMORIES.get(selected, [])
    operator_status = None
    if operator:
        with USERS_LOCK:
            op_data = USERS.get(operator)
        if op_data:
            if op_data.get('role') == 'admin' or op_data.get('approved'):
                operator_status = 'Operator'
            else:
                operator_status = 'SWL'
    now = time.time()
    with ACTIVE_LOCK:
        active_users = []
        for u, ts in list(ACTIVE_USERS.items()):
            if now - ts < 10:
                active_users.append((u, USER_RTT.get(u)))
            else:
                del ACTIVE_USERS[u]
                USER_RTT.pop(u, None)
        if user not in [u for u, _ in active_users]:
            active_users.append((user, USER_RTT.get(user)))
    return render_template(
        'index.html', rigs=rigs, selected_rig=selected,
        operator=operator, operator_status=operator_status,
        user=user, role=role,
        approved=approved, unapproved_count=unapproved_count,
        active_users=active_users, memories=memories,
        year=CURRENT_YEAR)

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
        return render_template('login.html', error='Ung\u00fcltige Zugangsdaten', year=CURRENT_YEAR)
    return render_template('login.html', year=CURRENT_YEAR)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        if not username or not password or not is_valid_callsign(username):
            return render_template('register.html', error='Ung\u00fcltige Eingabe', year=CURRENT_YEAR)
        with USERS_LOCK:
            if username in USERS:
                return render_template('register.html', error='Benutzer existiert bereits', year=CURRENT_YEAR)
            USERS[username] = {
                'password': generate_password_hash(password),
                'role': 'operator',
                'approved': False,
                'needs_change': False,
                'trx': False,
            }
            save_users()
        return render_template('login.html', message='Registrierung erfolgreich. Freischaltung abwarten.', year=CURRENT_YEAR)
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
        if not new_username or not password or (
            new_username != username and session.get('role') != 'admin' and not is_valid_callsign(new_username)
        ):
            return render_template('change_credentials.html', error='Ung\u00fcltige Eingabe', year=CURRENT_YEAR)
        with USERS_LOCK:
            if new_username != username and new_username in USERS:
                return render_template('change_credentials.html', error='Benutzer existiert bereits', year=CURRENT_YEAR)
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
    now = time.time()
    with ACTIVE_LOCK:
        for u, ts in list(ACTIVE_USERS.items()):
            if now - ts >= 10:
                del ACTIVE_USERS[u]
                USER_RTT.pop(u, None)
    return render_template('userlist.html', users=USERS, year=CURRENT_YEAR, role=role)


@app.route('/admin/create_user', methods=['GET', 'POST'])
def admin_create_user():
    """Allow an administrator to create a new user with any username."""
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    error = None
    user_data = {
        'role': 'operator',
        'approved': False,
        'trx': False,
    }
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = request.form.get('password') or ''
        role_val = request.form.get('role') or 'operator'
        approved = request.form.get('approved') == '1'
        trx = request.form.get('trx') == '1'
        if not username or not password:
            error = 'Ung\u00fcltige Eingabe'
        else:
            with USERS_LOCK:
                if username in USERS:
                    error = 'Benutzer existiert bereits'
                else:
                    USERS[username] = {
                        'password': generate_password_hash(password),
                        'role': role_val,
                        'approved': approved,
                        'needs_change': False,
                        'trx': trx,
                    }
                    save_users()
                    return redirect(url_for('admin_users'))
        user_data['role'] = role_val
        user_data['approved'] = approved
        user_data['trx'] = trx
    role = session.get('role')
    return render_template('create_user.html', user_data=user_data, year=CURRENT_YEAR, role=role, error=error)


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
            if not new_username:
                error = 'Ung\u00fcltige Eingabe'
            elif new_username != username and new_username in USERS:
                error = 'Benutzer existiert bereits'
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
        with USER_RIG_LOCK:
            USER_RIG.pop(user, None)
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
            user = session.get('user')
            if user:
                with USER_RIG_LOCK:
                    USER_RIG[user] = rig
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

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    if not session.get('logged_in'):
        return ('', 401)
    user = session.get('user')
    rtt = None
    if request.is_json:
        try:
            rtt = float(request.json.get('rtt')) if request.json.get('rtt') is not None else None
        except (TypeError, ValueError):
            rtt = None
    with ACTIVE_LOCK:
        ACTIVE_USERS[user] = time.time()
        if rtt is not None:
            USER_RTT[user] = rtt
    rig = session.get('rig')
    if rig:
        with USER_RIG_LOCK:
            USER_RIG[user] = rig
    broadcast_active_users()
    return ('', 204)

@app.route('/active_users')
def active_users_api():
    if not session.get('logged_in'):
        return ('', 401)
    if session.get('role') != 'admin':
        return ('', 403)
    now = time.time()
    with ACTIVE_LOCK:
        users = []
        for u, ts in list(ACTIVE_USERS.items()):
            if now - ts < 10:
                with USER_RIG_LOCK:
                    users.append((u, USER_RTT.get(u), USER_RIG.get(u)))
            else:
                del ACTIVE_USERS[u]
                USER_RTT.pop(u, None)
    return jsonify(users)

@app.route('/status_info')
def status_info():
    if not session.get('logged_in'):
        return ('', 401)
    with RIG_LOCK:
        rigs = list(RIGS.keys())
    selected = session.get('rig')
    if selected not in rigs and rigs:
        selected = rigs[0]
        session['rig'] = selected
    user = session.get('user')
    if user:
        with USER_RIG_LOCK:
            USER_RIG[user] = selected
    with OPERATOR_LOCK:
        operator = OPERATORS.get(selected)
    with MEMORY_LOCK:
        memories = RIG_MEMORIES.get(selected, [])
    operator_status = None
    if operator:
        with USERS_LOCK:
            op_data = USERS.get(operator)
        if op_data:
            if op_data.get('role') == 'admin' or op_data.get('approved'):
                operator_status = 'Operator'
            else:
                operator_status = 'SWL'
    return jsonify({
        'rigs': rigs,
        'selected': selected,
        'operator': operator,
        'operator_status': operator_status,
        'memories': memories
    })


@app.route('/answers')
def show_answers():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    role = session.get('role')
    answers = load_saved_answers()
    return render_template('answers.html', answers=answers, role=role,
                           year=CURRENT_YEAR)


@app.route('/fetch_answers')
def fetch_answers_route():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    answers = fetch_cat_answers()
    save_answers(answers)
    return redirect(url_for('show_answers'))

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
        elif cmd == 'encoder':
            if value in ('up', 'EU', 'down', 'ED'):
                code = 'EU' if value in ('up', 'EU') else 'ED'
                data = {'command': 'cat', 'data': f'{code};'}
            else:
                return ('', 204)
        elif cmd == 'mic_gain':
            try:
                gain = int(value)
                data = {'command': 'cat', 'data': f'MG{gain:03d};'}
            except ValueError:
                return ('', 204)
        elif cmd == 'memory_channel':
            try:
                ch = int(value)
                data = {'command': 'cat', 'data': f'MC{ch:03d};'}
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
        elif cmd == 'get_smeter':
            data = {'command': 'get_smeter'}
        else:
            return ('', 204)

        async def send():
            try:
                async with websockets.connect(REMOTE_SERVER) as ws:
                    await ws.send(json.dumps(data))
                    if cmd in ('get_frequency', 'get_mode', 'get_smeter'):
                        return await ws.recv()
            except Exception:
                logger.exception('Remote command failed')
                return None
            return None
        resp = asyncio.run(send())
        if resp is not None:
            return resp
        return ('Kein TRX verbunden', 200)
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
        elif cmd == 'encoder':
            if value in ('up', 'EU', 'down', 'ED'):
                code = 'EU' if value in ('up', 'EU') else 'ED'
                data = {'command': 'cat', 'data': f'{code};'}
            else:
                return ('', 204)
        elif cmd == 'mic_gain':
            try:
                gain = int(value)
                data = {'command': 'cat', 'data': f'MG{gain:03d};'}
            except ValueError:
                return ('', 204)
        elif cmd == 'memory_channel':
            try:
                ch = int(value)
                data = {'command': 'cat', 'data': f'MC{ch:03d};'}
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
        elif cmd == 'get_smeter':
            data = {'command': 'get_smeter'}
        else:
            return ('', 204)

        with RIG_LOCK:
            ws.send(json.dumps(data))
            if cmd in ('get_frequency', 'get_mode', 'get_smeter'):
                resp = ws.receive()
                if resp:
                    return resp
    else:
        return ('Kein TRX verbunden', 200)
    return ('', 204)

@sock.route('/ws/audio')
def audio(ws):
    rig = session.get('rig')
    rig_ws = None
    if rig:
        with RIG_AUDIO_LOCK:
            rig_ws = RIG_AUDIO.get(rig)
    if rig_ws is not None:
        with AUDIO_CLIENTS_LOCK:
            clients = AUDIO_CLIENTS.setdefault(rig, set())
            clients.add(ws)
        try:
            while True:
                msg = ws.receive()
                if msg is None:
                    break
                allow = False
                user = session.get('user')
                if rig and user:
                    with OPERATOR_LOCK:
                        allow = OPERATORS.get(rig) == user
                if allow:
                    try:
                        rig_ws.send(msg)
                    except Exception:
                        break
        finally:
            with AUDIO_CLIENTS_LOCK:
                AUDIO_CLIENTS.get(rig, set()).discard(ws)
    else:
        if pyaudio is None:
            ws.close()
            return
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
                    logger.exception('Failed to send audio chunk')
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
            logger.exception('Audio websocket error')
        finally:
            running = False
            input_stream.close()
            output_stream.close()
            p.terminate()

@sock.route('/ws/status')
def status(ws):
    with STATUS_LOCK:
        STATUS_CLIENTS.add(ws)
    with VALUES_LOCK:
        for rig, vals in RIG_VALUES.items():
            try:
                ws.send(json.dumps({'rig': rig, 'values': vals}))
            except Exception:
                pass
    with MEMORY_LOCK:
        for rig, mem in RIG_MEMORIES.items():
            try:
                ws.send(json.dumps({'rig': rig, 'memories': mem}))
            except Exception:
                pass
    try:
        while True:
            msg = ws.receive()
            if msg is None:
                break
    finally:
        with STATUS_LOCK:
            STATUS_CLIENTS.discard(ws)


@sock.route('/ws/active_users')
def active_users_ws(ws):
    if session.get('role') != 'admin':
        ws.close()
        return
    with ACTIVE_WS_LOCK:
        ACTIVE_WS_CLIENTS.add(ws)
    # send initial list
    now = time.time()
    with ACTIVE_LOCK:
        users = []
        for u, ts in list(ACTIVE_USERS.items()):
            if now - ts < 10:
                with USER_RIG_LOCK:
                    users.append((u, USER_RTT.get(u), USER_RIG.get(u)))
    try:
        ws.send(json.dumps({'active_users': users}))
        while True:
            msg = ws.receive()
            if msg is None:
                break
    finally:
        with ACTIVE_WS_LOCK:
            ACTIVE_WS_CLIENTS.discard(ws)

def main():
    global REMOTE_SERVER
    parser = argparse.ArgumentParser(description='FT-991A remote server')
    parser.add_argument('--server', default=DEFAULT_REMOTE_SERVER,
                        help='Remote control server ws://host:port')
    parser.add_argument('--secret', default=DEFAULT_SECRET,
                        help='Flask secret key')
    parser.add_argument('--input-device', type=int, default=None,
                        help='Audio input device index')
    parser.add_argument('--output-device', type=int, default=None,
                        help='Audio output device index')
    parser.add_argument('--list-devices', action='store_true',
                        help='List audio devices and exit')
    args = parser.parse_args()

    app.secret_key = args.secret
    global INPUT_DEVICE_INDEX, OUTPUT_DEVICE_INDEX
    INPUT_DEVICE_INDEX = args.input_device
    OUTPUT_DEVICE_INDEX = args.output_device

    if args.list_devices:
        if pyaudio is None:
            print('pyaudio not installed')
        else:
            p = pyaudio.PyAudio()
            for i in range(p.get_device_count()):
                info = p.get_device_info_by_index(i)
                print(f"{i}: {info['name']}")
            p.terminate()
        return

    REMOTE_SERVER = args.server
    # The web interface always runs on port 8084
    app.run(host='0.0.0.0', port=8084)


if __name__ == '__main__':
    main()
