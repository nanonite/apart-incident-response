"""Private IPC transport for controller-owned constrained tool services."""

from __future__ import annotations

import json
import os
import select
import socket
import stat
import threading
from pathlib import Path
from typing import Any, Mapping

from .tool_contract import MAX_TOOL_REQUEST_BYTES, ToolServiceError


class ToolServiceSocketServer:
    """Expose a service over a private Unix socket or fixture FIFO pair."""

    def __init__(
        self,
        service: Any,
        socket_path: Path,
        *,
        use_fifo: bool = False,
    ) -> None:
        self._service = service
        self.socket_path = socket_path.expanduser().resolve()
        self._use_fifo = use_fifo
        if len(str(self.socket_path)) >= 100:
            raise ToolServiceError("tool service socket path is too long")
        self._socket: socket.socket | None = None
        self.request_fifo = Path(f"{self.socket_path}.request")
        self.response_fifo = Path(f"{self.socket_path}.response")
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            raise ToolServiceError("tool service server already started")
        if self._use_fifo:
            self._start_fifo()
            return
        self._prepare_socket_path()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(os.fspath(self.socket_path))
            os.chmod(self.socket_path, stat.S_IRUSR | stat.S_IWUSR)
            server.listen(8)
            server.settimeout(0.2)
        except OSError:
            server.close()
            raise
        self._socket = server
        self._thread = threading.Thread(target=self._serve, name="apart-tool-service", daemon=True)
        self._thread.start()

    def _start_fifo(self) -> None:
        self._prepare_fifo(self.request_fifo)
        self._prepare_fifo(self.response_fifo)
        self._thread = threading.Thread(
            target=self._serve_fifo, name="apart-tool-service", daemon=True
        )
        self._thread.start()

    @staticmethod
    def _prepare_fifo(path: Path) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists():
            if path.is_symlink() or not stat.S_ISFIFO(path.stat().st_mode):
                raise ToolServiceError("refusing to replace a non-FIFO tool service path")
            path.unlink()
        os.mkfifo(path, stat.S_IRUSR | stat.S_IWUSR)

    def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        for path in (self.socket_path, self.request_fifo, self.response_fifo):
            try:
                path.unlink()
            except FileNotFoundError:
                continue

    @property
    def uses_fifo(self) -> bool:
        return self._use_fifo

    def request_from_controller(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Send one request through the private test or production endpoint."""

        payload = (json.dumps(request) + "\n").encode("utf-8")
        if self._use_fifo:
            with self.request_fifo.open("wb") as request_stream:
                request_stream.write(payload)
            with self.response_fifo.open("rb") as response_stream:
                value = json.loads(response_stream.readline())
        else:
            value = self._request_over_socket(payload)
        if not isinstance(value, Mapping):
            raise ToolServiceError("tool service returned an invalid response")
        return value

    def _request_over_socket(self, payload: bytes) -> Any:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(5.0)
            client.connect(os.fspath(self.socket_path))
            client.sendall(payload)
            data = bytearray()
            while len(data) <= MAX_TOOL_REQUEST_BYTES:
                chunk = client.recv(4096)
                if not chunk:
                    break
                data.extend(chunk)
                if b"\n" in chunk:
                    break
        if len(data) > MAX_TOOL_REQUEST_BYTES:
            raise ToolServiceError("tool service response exceeded the size limit")
        try:
            return json.loads(bytes(data).split(b"\n", 1)[0])
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ToolServiceError("tool service returned an invalid response") from exc

    def _prepare_socket_path(self) -> None:
        self.socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not self.socket_path.exists():
            return
        if self.socket_path.is_symlink() or not stat.S_ISSOCK(self.socket_path.stat().st_mode):
            raise ToolServiceError("refusing to replace a non-socket tool service path")
        self.socket_path.unlink()

    def _serve(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                connection, _ = self._socket.accept()
            except (OSError, ValueError):
                continue
            threading.Thread(target=self._handle, args=(connection,), daemon=True).start()

    def _serve_fifo(self) -> None:
        while not self._stop.is_set():
            try:
                descriptor = os.open(self.request_fifo, os.O_RDONLY | os.O_NONBLOCK)
                readable, _, _ = select.select([descriptor], [], [], 0.2)
                if not readable:
                    os.close(descriptor)
                    continue
                request = os.read(descriptor, MAX_TOOL_REQUEST_BYTES + 1)
                os.close(descriptor)
                if request:
                    response = self._decode_request(request)
                    with self.response_fifo.open("wb") as response_stream:
                        response_stream.write((json.dumps(response) + "\n").encode("utf-8"))
            except OSError:
                if self._stop.is_set():
                    return

    def _decode_request(self, data: bytes) -> Mapping[str, Any]:
        if len(data) > MAX_TOOL_REQUEST_BYTES:
            return self._invalid_request()
        try:
            value = json.loads(data.split(b"\n", 1)[0])
        except (UnicodeDecodeError, json.JSONDecodeError):
            return self._invalid_request()
        if not isinstance(value, Mapping) or set(value) != {"credential", "operation", "arguments"}:
            return self._invalid_request()
        return self._service.invoke(value.get("credential"), value.get("operation"), value.get("arguments"))

    @staticmethod
    def _invalid_request() -> Mapping[str, Any]:
        return {"ok": False, "error": {"code": "invalid_request", "message": "invalid request"}}

    def _handle(self, connection: socket.socket) -> None:
        with connection:
            request = self._read_request(connection)
            if request is None or set(request) != {"credential", "operation", "arguments"}:
                self._send(connection, self._invalid_request())
                return
            response = self._service.invoke(
                request.get("credential"), request.get("operation"), request.get("arguments")
            )
            self._send(connection, response)

    @staticmethod
    def _read_request(connection: socket.socket) -> Mapping[str, Any] | None:
        data = bytearray()
        while len(data) <= MAX_TOOL_REQUEST_BYTES:
            try:
                chunk = connection.recv(4096)
            except OSError:
                return None
            if not chunk:
                break
            data.extend(chunk)
            if b"\n" in chunk:
                break
        if len(data) > MAX_TOOL_REQUEST_BYTES:
            return None
        try:
            value = json.loads(bytes(data).split(b"\n", 1)[0])
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return value if isinstance(value, Mapping) else None

    @staticmethod
    def _send(connection: socket.socket, response: Mapping[str, Any]) -> None:
        try:
            connection.sendall((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        except OSError:
            return

    def __enter__(self) -> "ToolServiceSocketServer":
        self.start()
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.stop()
