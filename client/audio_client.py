import socket
import pyaudio

AUDIO_RATE = 16000
AUDIO_FORMAT = pyaudio.paInt16
CHANNELS = 1
CHUNK = 1024


def run_audio_client(server_ip="127.0.0.1", server_port=9003, client_port=9002):
    """Start bidirectional audio streaming."""

    p = pyaudio.PyAudio()
    input_stream = p.open(
        format=AUDIO_FORMAT,
        channels=CHANNELS,
        rate=AUDIO_RATE,
        input=True,
        frames_per_buffer=CHUNK,
    )
    output_stream = p.open(
        format=AUDIO_FORMAT,
        channels=CHANNELS,
        rate=AUDIO_RATE,
        output=True,
        frames_per_buffer=CHUNK,
    )

    sock_tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock_rx.bind(("0.0.0.0", client_port))

    print("Audio client running (Ctrl+C to stop)")
    try:
        while True:
            data = input_stream.read(CHUNK, exception_on_overflow=False)
            sock_tx.sendto(data, (server_ip, server_port))
            try:
                packet, _ = sock_rx.recvfrom(CHUNK * 2)
                output_stream.write(packet)
            except socket.error:
                pass
    except KeyboardInterrupt:
        print("Stopping audio client")
    finally:
        input_stream.close()
        output_stream.close()
        sock_tx.close()
        sock_rx.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FT-991A audio client")
    parser.add_argument("--server", default="127.0.0.1", help="Server IP")
    parser.add_argument("--sport", type=int, default=9003, help="Server UDP port")
    parser.add_argument("--cport", type=int, default=9002, help="Client UDP port")
    args = parser.parse_args()

    run_audio_client(args.server, args.sport, args.cport)
