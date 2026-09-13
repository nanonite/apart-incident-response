"""Loopback-to-Unix bridge used inside the Pi network namespace.

The controller owns the policy-enforcing relay. This process only gives Pi a
normal HTTP proxy endpoint inside its private namespace and forwards opaque
proxy bytes over the controller-owned Unix socket.
"""

from __future__ import annotations

import argparse
import os
import socket
import socketserver
import subprocess
import sys
import threading
from pathlib import Path


class _BridgeHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        socket_path = Path(self.server.socket_path)  # type: ignore[attr-defined]
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            upstream.connect(str(socket_path))
            self.server.relay(self.request, upstream)  # type: ignore[attr-defined]
        finally:
            upstream.close()


class _BridgeServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], socket_path: Path) -> None:
        self.socket_path = socket_path
        super().__init__(address, _BridgeHandler)

    @staticmethod
    def relay(left: socket.socket, right: socket.socket) -> None:
        import select

        open_sockets = [left, right]
        while open_sockets:
            readable, _, _ = select.select(open_sockets, [], [], 30)
            if not readable:
                return
            for source in readable:
                payload = source.recv(64 * 1024)
                destination = right if source is left else left
                if not payload:
                    try:
                        destination.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    open_sockets.remove(source)
                    continue
                destination.sendall(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--local-port", type=int)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if not args.command or args.command[0] != "--":
        parser.error("a Pi command is required after --")

    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.local_port is not None and not 1 <= args.local_port <= 65535:
        parser.error("--local-port must be between 1 and 65535")
    if args.local_port == args.port:
        parser.error("--local-port must differ from --port")

    servers = [_BridgeServer(("127.0.0.1", args.port), args.socket)]
    if args.local_port is not None:
        servers.append(_BridgeServer(("127.0.0.1", args.local_port), args.socket))
    serving = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in servers
    ]
    for thread in serving:
        thread.start()
    child = subprocess.Popen(
        args.command[1:],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=os.environ.copy(),
        close_fds=True,
    )
    try:
        return child.wait()
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=2)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
