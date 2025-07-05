import socket
import pyaudio

AUDIO_RATE = 16000
AUDIO_FORMAT = pyaudio.paInt16
CHANNELS = 1
CHUNK = 1024

SERVER_IP = '127.0.0.1'
CLIENT_PORT = 9002
SERVER_PORT = 9003

p = pyaudio.PyAudio()
input_stream = p.open(format=AUDIO_FORMAT, channels=CHANNELS, rate=AUDIO_RATE,
                      input=True, frames_per_buffer=CHUNK)
output_stream = p.open(format=AUDIO_FORMAT, channels=CHANNELS, rate=AUDIO_RATE,
                       output=True, frames_per_buffer=CHUNK)

sock_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_rx.bind(('0.0.0.0', CLIENT_PORT))

print('Audio client running')
while True:
    data = input_stream.read(CHUNK, exception_on_overflow=False)
    sock_tx.sendto(data, (SERVER_IP, SERVER_PORT))
    try:
        packet, _ = sock_rx.recvfrom(CHUNK * 2)
        output_stream.write(packet)
    except socket.error:
        pass
