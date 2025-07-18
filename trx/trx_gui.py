import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import threading
import asyncio
from queue import Queue, Empty
import serial.tools.list_ports
import pyaudio
import websockets
from serial import SerialException
import datetime
import subprocess
import locale

import ft991a_ws_server as trx

CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CURRENT_YEAR = datetime.datetime.now().year


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


def _decode_device_name(name):
    """Geraetenamen robust in Unicode wandeln."""
    if isinstance(name, bytes):
        for enc in ('utf-8', locale.getpreferredencoding(False), 'cp1252'):
            try:
                return name.decode(enc)
            except Exception:
                pass
        return name.decode('utf-8', errors='replace')
    return str(name)


def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(cfg):
    """Konfiguration UTF-8 speichern."""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class App:
    def __init__(self, root):
        self.root = root
        root.title(PROGRAM_VERSION)
        cfg = load_config()

        self.queue = Queue()
        self.ws_thread = None
        self.stop_event = threading.Event()

        frame = ttk.Frame(root, padding=10)
        frame.pack(fill='both', expand=True)

        row = 0
        ttk.Label(frame, text='Server').grid(row=row, column=0, sticky='e')
        self.server_var = tk.StringVar(value=cfg.get('server', trx.DEFAULT_CONNECT_URI))
        ttk.Entry(frame, textvariable=self.server_var, width=40).grid(row=row, column=1, sticky='w')
        row += 1

        ttk.Label(frame, text='Callsign').grid(row=row, column=0, sticky='e')
        self.callsign_var = tk.StringVar(value=cfg.get('callsign', trx.DEFAULT_CALLSIGN))
        ttk.Entry(frame, textvariable=self.callsign_var).grid(row=row, column=1, sticky='w')
        row += 1

        ttk.Label(frame, text='Benutzer').grid(row=row, column=0, sticky='e')
        self.user_var = tk.StringVar(value=cfg.get('username', ''))
        ttk.Entry(frame, textvariable=self.user_var).grid(row=row, column=1, sticky='w')
        row += 1

        ttk.Label(frame, text='Passwort').grid(row=row, column=0, sticky='e')
        self.pw_var = tk.StringVar(value=cfg.get('password', ''))
        ttk.Entry(frame, textvariable=self.pw_var, show='*').grid(row=row, column=1, sticky='w')
        row += 1

        ttk.Label(frame, text='COM-Port').grid(row=row, column=0, sticky='e')
        self.port_var = tk.StringVar(value=cfg.get('serial_port', trx.DEFAULT_SERIAL_PORT))
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if not ports:
            ports = [trx.DEFAULT_SERIAL_PORT]
        self.port_combo = ttk.Combobox(frame, textvariable=self.port_var, values=ports, width=15)
        self.port_combo.grid(row=row, column=1, sticky='w')
        row += 1

        ttk.Label(frame, text='Baudrate').grid(row=row, column=0, sticky='e')
        self.baud_var = tk.StringVar(value=str(cfg.get('baudrate', trx.DEFAULT_BAUDRATE)))
        baudrates = ["9600", "19200", "38400", "57600", "115200"]
        self.baud_combo = ttk.Combobox(frame, textvariable=self.baud_var, values=baudrates, width=15)
        self.baud_combo.grid(row=row, column=1, sticky='w')
        row += 1

        ttk.Label(frame, text='Input-Audio').grid(row=row, column=0, sticky='e')
        self.in_var = tk.IntVar(value=cfg.get('input_device', -1))
        ttk.Label(frame, textvariable=tk.StringVar()).grid(row=row, column=2)
        input_row = row
        row += 1

        ttk.Label(frame, text='Output-Audio').grid(row=row, column=0, sticky='e')
        self.out_var = tk.IntVar(value=cfg.get('output_device', -1))
        ttk.Label(frame, textvariable=tk.StringVar()).grid(row=row, column=2)
        output_row = row
        row += 1

        # Audio-Geraetelisten getrennt nach Input und Output erstellen
        p = pyaudio.PyAudio()
        input_devices = []
        output_devices = []
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            name = _decode_device_name(info['name'])
            entry = f"{i}: {name}"
            if info.get('maxInputChannels', 0) > 0:
                input_devices.append(entry)
            if info.get('maxOutputChannels', 0) > 0:
                output_devices.append(entry)
        p.terminate()

        input_width = max((len(d) for d in input_devices), default=40)
        self.input_combo = ttk.Combobox(frame, values=input_devices, width=input_width)
        self.input_combo.grid(row=input_row, column=1, sticky='w')
        for pos, dev in enumerate(input_devices):
            if int(dev.split(':')[0]) == self.in_var.get():
                self.input_combo.current(pos)
                break

        output_width = max((len(d) for d in output_devices), default=40)
        self.output_combo = ttk.Combobox(frame, values=output_devices, width=output_width)
        self.output_combo.grid(row=output_row, column=1, sticky='w')
        for pos, dev in enumerate(output_devices):
            if int(dev.split(':')[0]) == self.out_var.get():
                self.output_combo.current(pos)
                break

        self.start_btn = ttk.Button(frame, text='Remote starten', command=self.start)
        self.start_btn.grid(row=row, column=0, columnspan=2, pady=5)
        row += 1

        self.stop_btn = ttk.Button(frame, text='Remote beenden', command=self.stop)
        self.stop_btn.grid(row=row, column=0, columnspan=2, pady=5)
        row += 1

        ttk.Label(frame, text='Verbundene Nutzer:').grid(row=row, column=0, sticky='nw')
        self.users_text = tk.Text(frame, width=40, height=5, state='disabled')
        self.users_text.grid(row=row, column=1, sticky='w')
        row += 1

        ttk.Label(frame, text=f"{PROGRAM_VERSION} - © {CURRENT_YEAR} Erik Schauer, do1ffe@darc.de")\
            .grid(row=row, column=0, columnspan=2, pady=5)

        self.validate()

    def validate(self, *_):
        valid = all([
            self.server_var.get().strip(),
            self.callsign_var.get().strip(),
            self.user_var.get().strip(),
            self.pw_var.get(),
            self.port_var.get().strip(),
            self.baud_combo.get(),
            self.input_combo.get(),
            self.output_combo.get(),
        ])
        state = 'normal' if valid and not self.ws_thread else 'disabled'
        self.start_btn.config(state=state)
        self.root.after(500, self.validate)

    def start(self):
        cfg = {
            'server': self.server_var.get().strip(),
            'callsign': self.callsign_var.get().strip(),
            'username': self.user_var.get().strip(),
            'password': self.pw_var.get(),
            'serial_port': self.port_var.get().strip(),
            'baudrate': int(self.baud_combo.get()),
            'input_device': int(self.input_combo.get().split(':')[0]),
            'output_device': int(self.output_combo.get().split(':')[0]),
        }
        save_config(cfg)
        self.stop_event.clear()
        self.ws_thread = threading.Thread(target=self.run_async, args=(cfg,), daemon=True)
        self.ws_thread.start()
        self.poll_queue()

    def stop(self):
        if not messagebox.askyesno('Remote beenden',
                                   'Sind Sie sicher, das Programm zu beenden?'):
            return
        self.stop_event.set()
        if self.ws_thread and self.ws_thread.is_alive():
            self.ws_thread.join(timeout=1)
        if trx.ser:
            try:
                trx.ser.close()
            except Exception:
                pass
            trx.ser = None
        self.root.destroy()

    def poll_queue(self):
        try:
            while True:
                msg = self.queue.get_nowait()
                if msg[0] == 'users':
                    self.users_text.config(state='normal')
                    self.users_text.delete('1.0', 'end')
                    self.users_text.insert('end', '\n'.join(msg[1]))
                    self.users_text.config(state='disabled')
        except Empty:
            pass
        if self.ws_thread and self.ws_thread.is_alive():
            self.root.after(500, self.poll_queue)

    def run_async(self, cfg):
        asyncio.run(self.async_main(cfg))

    async def async_main(self, cfg):
        trx.CALLSIGN = cfg['callsign']
        try:
            baud = cfg.get('baudrate', trx.DEFAULT_BAUDRATE)
            trx.ser = trx.open_serial_autodetect(cfg['serial_port'], baud)
        except SerialException:
            self.queue.put(('users', ['Dummy-TRX aktiv']))
            trx.ser = trx.DummySerial()
        handshake = {
            'callsign': cfg['callsign'],
            'username': cfg['username'],
            'password': cfg['password'],
            'mode': 'trx'
        }
        server_uri = cfg['server']
        active_uri = server_uri.rsplit('/', 1)[0] + '/active_users'

        async def users_loop():
            while not self.stop_event.is_set():
                try:
                    async with websockets.connect(active_uri) as ws:
                        async for msg in ws:
                            data = json.loads(msg)
                            users = [
                                u[0] for u in data.get('active_users', [])
                                if len(u) < 3 or u[2] == cfg['callsign']
                            ]
                            self.queue.put(('users', users))
                except Exception:
                    await asyncio.sleep(1)

        async def run_client():
            await trx.client_loop(server_uri, handshake)

        async def run_audio():
            audio_handshake = {
                'callsign': cfg['callsign'],
                'username': cfg['username'],
                'password': cfg['password'],
                'mode': 'trx_audio'
            }
            await trx.audio_loop(server_uri.rsplit('/',1)[0]+'/rig_audio',
                                audio_handshake,
                                cfg['input_device'],
                                cfg['output_device'])
        await asyncio.gather(users_loop(), run_client(), run_audio())


def main():
    root = tk.Tk()
    app = App(root)
    root.protocol('WM_DELETE_WINDOW', app.stop)
    root.mainloop()


if __name__ == '__main__':
    main()
