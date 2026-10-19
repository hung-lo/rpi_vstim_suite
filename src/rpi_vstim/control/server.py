"""Owner-only JSON-lines Unix socket for reliable local experiment control."""

from __future__ import annotations

import errno
import json
import os
import socket
import stat
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

MAX_REQUEST_BYTES = 16_384


def default_control_socket_path(session_id: str) -> Path:
    safe_id = "".join(char if char.isalnum() or char in "_.-" else "_" for char in session_id)
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    root = Path(runtime) / "rpi-vstim" if runtime else Path("/tmp") / f"rpi-vstim-{os.getuid()}"
    return root / f"{safe_id}.sock"


class UnixControlServer:
    def __init__(self, path: Path, handler: Callable[[object], dict[str, Any]]) -> None:
        self.path = Path(path)
        self.handler = handler
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._created_identity: tuple[int, int] | None = None

    def start(self) -> None:
        encoded = os.fsencode(self.path)
        if len(encoded) >= 108:
            raise ValueError("control socket path exceeds the Unix socket path limit")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent != Path("/tmp") and self.path.parent.name in {
            f"rpi-vstim-{os.getuid()}", "rpi-vstim"
        }:
            os.chmod(self.path.parent, 0o700)
        self._remove_stale_socket()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound = False
        try:
            server.bind(str(self.path))
            bound = True
            os.chmod(self.path, 0o600)
            info = self.path.lstat()
            self._created_identity = (info.st_dev, info.st_ino)
            server.listen(8)
            server.settimeout(0.2)
        except BaseException:
            server.close()
            if bound:
                self.path.unlink(missing_ok=True)
            raise
        self._socket = server
        self._thread = threading.Thread(target=self._serve, name="rpi-vstim-control", daemon=True)
        self._thread.start()

    def _remove_stale_socket(self) -> None:
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
            raise FileExistsError(f"refusing to replace non-owned control socket path: {self.path}")
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.2)
            probe.connect(str(self.path))
        except OSError as exc:
            if exc.errno not in {errno.ECONNREFUSED, errno.ENOENT}:
                raise FileExistsError(f"control socket may still be active: {self.path}") from exc
            current = self.path.lstat()
            if (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino):
                self.path.unlink()
        else:
            raise FileExistsError(f"control socket is already active: {self.path}")
        finally:
            probe.close()

    def _serve(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                client, _ = self._socket.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with client:
                try:
                    client.settimeout(1.0)
                    request = self._read_request(client)
                    response = self.handler(request)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    response = {
                        "schema_version": 1,
                        "request_id": None,
                        "ok": False,
                        "error": {"code": "invalid_request", "message": str(exc)},
                    }
                try:
                    client.sendall(json.dumps(response, separators=(",", ":")).encode() + b"\n")
                except OSError:
                    pass

    @staticmethod
    def _read_request(client: socket.socket) -> object:
        chunks = bytearray()
        deadline = time.monotonic() + 2.0
        while len(chunks) <= MAX_REQUEST_BYTES:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("request timed out before newline")
            client.settimeout(remaining)
            chunk = client.recv(min(4096, MAX_REQUEST_BYTES + 1 - len(chunks)))
            if not chunk:
                break
            newline = chunk.find(b"\n")
            chunks.extend(chunk if newline < 0 else chunk[:newline])
            if newline >= 0:
                if chunk[newline + 1 :].strip():
                    raise ValueError("one JSON request is allowed per connection")
                break
        if len(chunks) > MAX_REQUEST_BYTES:
            raise ValueError("request exceeds maximum size")
        if not chunks:
            raise ValueError("empty request")
        try:
            return json.loads(chunks)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid JSON request: {exc}") from exc

    def close(self) -> None:
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        try:
            info = self.path.lstat()
        except FileNotFoundError:
            return
        if self._created_identity == (info.st_dev, info.st_ino):
            self.path.unlink(missing_ok=True)

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
