"""Open a video in a desktop player, detached from the MCP server process."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


class PlayerError(RuntimeError):
    pass


def _split_command(command: str) -> list[str]:
    if os.name != "nt":
        return shlex.split(command)
    # Non-POSIX shlex keeps the quotes around "C:\Program Files\...\vlc.exe".
    return [
        part[1:-1] if len(part) > 1 and part[0] == part[-1] == '"' else part
        for part in shlex.split(command, posix=False)
    ]


def _spawn(command: list[str]) -> None:
    kwargs = {"start_new_session": True} if os.name == "posix" else {}
    try:
        # The stdio transport speaks MCP over stdout, so the player must never
        # inherit it.
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **kwargs,
        )
    except OSError as exc:
        raise PlayerError(f"Could not start {command[0]}: {exc}") from exc


def play(path: Path, player: str = "auto") -> str:
    """Start playback and return the name of the player that was used."""
    if player != "auto":
        command = _split_command(player)
        if not command:
            raise PlayerError("VIDEO_PLAYER is set but empty")
        _spawn([*command, str(path)])
        return command[0]

    for name in ("mpv", "vlc"):
        executable = shutil.which(name)
        if executable:
            _spawn([executable, str(path)])
            return name

    if sys.platform == "win32":
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except OSError as exc:
            raise PlayerError(f"Could not open {path}: {exc}") from exc
        return "system default"

    opener = shutil.which("open" if sys.platform == "darwin" else "xdg-open")
    if opener is None:
        raise PlayerError("No video player found. Install mpv or VLC, or set VIDEO_PLAYER.")
    _spawn([opener, str(path)])
    return "system default"
