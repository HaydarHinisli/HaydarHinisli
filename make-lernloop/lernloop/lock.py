"""Schutz vor gleichzeitig gestarteten Lernsitzungen (exklusive Sperrdatei)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


class LockHeld(Exception):
    pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)  # Signal 0 prüft nur, ob der Prozess existiert
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class SessionLock:
    """Sperrdatei mit PID. Eine verwaiste Sperre (Prozess beendet) wird übernommen."""

    def __init__(self, path: Path, purpose: str):
        self.path = path
        self.purpose = purpose
        self.stale_previous: dict | None = None

    def __enter__(self) -> "SessionLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "purpose": self.purpose,
                "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        ).encode()
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                info = self._read()
                if info and _pid_alive(int(info.get("pid", -1))):
                    raise LockHeld(
                        f"Es läuft bereits ein Vorgang ({info.get('purpose')}, PID {info.get('pid')}, "
                        f"seit {info.get('started_at')})."
                    )
                self.stale_previous = info
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
            return self
        raise LockHeld("Sperrdatei konnte nicht angelegt werden.")

    def _read(self) -> dict | None:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return None

    def __exit__(self, *exc) -> None:
        info = self._read()
        if info and info.get("pid") == os.getpid():
            self.path.unlink(missing_ok=True)
