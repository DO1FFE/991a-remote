import asyncio
import json
import tkinter as tk
from tkinter import ttk
import websockets

class RemoteClientGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FT-991A Remote")
        self.geometry("300x250")

        self.server_ip = tk.StringVar(value="127.0.0.1")
        self.frequency = tk.StringVar()
        self.mode = tk.StringVar()
        self.status = tk.StringVar()

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

if __name__ == "__main__":
    app = RemoteClientGUI()
    app.mainloop()
