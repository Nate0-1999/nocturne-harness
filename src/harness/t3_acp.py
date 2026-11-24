"""The front T3 server's local ACP command. Only the daemon runs turns."""

import json
import os
import select
import socket
import sys


def main():
    with socket.socket(socket.AF_UNIX) as channel:
        channel.connect(sys.argv[1])
        # T3 also starts the command without a thread to discover its capabilities.
        channel.sendall(json.dumps(os.environ.get("T3CODE_THREAD_ID")).encode() + b"\n")
        while True:
            ready, _, _ = select.select([sys.stdin.buffer, channel], [], [])
            if channel in ready:
                data = channel.recv(65536)
                if not data:
                    break
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            if sys.stdin.buffer in ready:
                data = os.read(0, 65536)
                if not data:
                    break
                channel.sendall(data)


if __name__ == "__main__":
    main()
