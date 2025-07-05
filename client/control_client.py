import asyncio
import json
import sys
import websockets

SERVER_IP = '127.0.0.1'

async def send_command(command):
    uri = f'ws://{SERVER_IP}:9001'
    try:
        async with websockets.connect(uri) as websocket:
            await websocket.send(json.dumps(command))
            if command.get('command') == 'get_frequency':
                resp = await websocket.recv()
                print(resp)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--freq', type=int, help='Set frequency in Hz')
    parser.add_argument('--mode', type=int, help='Set mode number')
    parser.add_argument('--ptt', choices=['on', 'off'], help='Key PTT on/off')
    parser.add_argument('--query', action='store_true', help='Query frequency')
    parser.add_argument('--server', default='127.0.0.1', help='Server IP')
    args = parser.parse_args()
    SERVER_IP = args.server

    commands = []
    if args.freq:
        commands.append({'command': 'set_frequency', 'frequency': args.freq})
    if args.mode is not None:
        commands.append({'command': 'set_mode', 'mode': args.mode})
    if args.ptt == 'on':
        commands.append({'command': 'ptt_on'})
    if args.ptt == 'off':
        commands.append({'command': 'ptt_off'})
    if args.query:
        commands.append({'command': 'get_frequency'})

    if not commands:
        parser.print_help()
        sys.exit(0)

    async def run():
        for cmd in commands:
            await send_command(cmd)

    asyncio.run(run())
