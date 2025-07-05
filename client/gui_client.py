import asyncio
import json
import os
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
import websockets

class RemoteClientGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FT-991A Remote")
        self.geometry("320x420")

        self.server_ip = tk.StringVar(value="127.0.0.1")
        self.frequency = tk.StringVar()
        self.mode = tk.StringVar()
        self.audio_server_ip = tk.StringVar(value="127.0.0.1")
        self.audio_server_port = tk.StringVar(value="9003")
        self.audio_client_port = tk.StringVar(value="9002")
        self.status = tk.StringVar()
        self.audio_process = None

        tk.Label(self, text="Server IP:").pack(pady=2)
        tk.Entry(self, textvariable=self.server_ip).pack(pady=2)

        tk.Label(self, text="Frequenz (Hz):").pack(pady=2)
        tk.Entry(self, textvariable=self.frequency).pack(pady=2)
        tk.Button(self, text="Set Frequency", command=self.set_frequency).pack(pady=2)

        tk.Label(self, text="Mode Nr.:").pack(pady=2)
        modes = ["1", "2", "3", "7"]
        ttk.Combobox(self, values=modes, textvariable=self.mode).pack(pady=2)
        tk.Button(self, text="Set Mode", command=self.set_mode).pack(pady=2)

        tk.Button(self, text="PTT ON", command=self.ptt_on).pack(pady=2)
        tk.Button(self, text="PTT OFF", command=self.ptt_off).pack(pady=2)

        tk.Button(self, text="Query Frequency", command=self.query_frequency).pack(pady=2)

        tk.Label(self, text="Audio Server IP:").pack(pady=2)
        tk.Entry(self, textvariable=self.audio_server_ip).pack(pady=2)
        tk.Label(self, text="Audio Server Port:").pack(pady=2)
        tk.Entry(self, textvariable=self.audio_server_port).pack(pady=2)
        tk.Label(self, text="Audio Client Port:").pack(pady=2)
        tk.Entry(self, textvariable=self.audio_client_port).pack(pady=2)
        tk.Button(self, text="Start Audio", command=self.start_audio).pack(pady=2)
        tk.Button(self, text="Stop Audio", command=self.stop_audio).pack(pady=2)

        tk.Label(self, textvariable=self.status).pack(pady=2)

    def send_command(self, command):
        async def _send():
            uri = f"ws://{self.server_ip.get()}:9001"
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps(command))
                if command.get("command") == "get_frequency":
                    resp = await ws.recv()
                    freq = json.loads(resp).get("frequency", "")
                    self.status.set(f"Freq: {freq}")
        try:
            asyncio.run(_send())
        except Exception as e:
            self.status.set(str(e))

    def set_frequency(self):
        try:
            freq = int(self.frequency.get())
        except ValueError:
            self.status.set("Invalid frequency")
            return
        self.send_command({"command": "set_frequency", "frequency": freq})

    def set_mode(self):
        try:
            mode = int(self.mode.get())
        except ValueError:
            self.status.set("Invalid mode")
            return
        self.send_command({"command": "set_mode", "mode": mode})

    def ptt_on(self):
        self.send_command({"command": "ptt_on"})

    def ptt_off(self):
        self.send_command({"command": "ptt_off"})

    def query_frequency(self):
        self.send_command({"command": "get_frequency"})

    def start_audio(self):
        if self.audio_process is not None:
            self.status.set("Audio already running")
            return
        script = os.path.join(os.path.dirname(__file__), "audio_client.py")
        cmd = [
            sys.executable,
            script,
            "--server",
            self.audio_server_ip.get(),
            "--sport",
            self.audio_server_port.get(),
            "--cport",
            self.audio_client_port.get(),
        ]
        try:
            self.audio_process = subprocess.Popen(cmd)
            self.status.set("Audio started")
        except Exception as e:
            self.status.set(str(e))

    def stop_audio(self):
        if self.audio_process is not None:
            self.audio_process.terminate()
            self.audio_process.wait()
            self.audio_process = None
            self.status.set("Audio stopped")

if __name__ == "__main__":
    app = RemoteClientGUI()
    app.mainloop()
