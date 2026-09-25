"""Configuration, read from environment variables.

MCP clients (LM Studio, Open WebUI, Jan, ...) pass settings to a server via
the `env` block of their config, so environment variables are the one
mechanism every client supports.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_TRUTHY = frozenset({"1", "true", "yes", "ja", "on"})
_FALSY = frozenset({"0", "false", "no", "nein", "off"})


def _parse_bool(value: str | None, *, default: bool, name: str) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in _TRUTHY:
        return True
    if normalized in _FALSY:
        return False
    raise ValueError(f"{name}: cannot interpret {value!r} as true/false")


def default_db_path(env: Mapping[str, str]) -> Path:
    if os.name == "nt" and env.get("LOCALAPPDATA"):
        base = Path(env["LOCALAPPDATA"])
    elif env.get("XDG_DATA_HOME"):
        base = Path(env["XDG_DATA_HOME"])
    else:
        base = Path.home() / ".local" / "share"
    return base / "local-video-mcp" / "library.db"


@dataclass(frozen=True)
class Config:
    library_paths: tuple[Path, ...]
    db_path: Path
    player: str = "auto"
    age_confirmed: bool = False
    probe_duration: bool = True

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env
        raw_paths = env.get("VIDEO_LIBRARY_PATHS", "")
        library_paths = tuple(
            Path(p).expanduser().resolve() for p in raw_paths.split(os.pathsep) if p.strip()
        )
        db_path = Path(env["VIDEO_DB_PATH"]).expanduser() if env.get("VIDEO_DB_PATH") else default_db_path(env)
        return cls(
            library_paths=library_paths,
            db_path=db_path,
            player=env.get("VIDEO_PLAYER", "").strip() or "auto",
            age_confirmed=_parse_bool(
                env.get("VIDEO_AGE_CONFIRMED"), default=False, name="VIDEO_AGE_CONFIRMED"
            ),
            probe_duration=_parse_bool(
                env.get("VIDEO_PROBE_DURATION"), default=True, name="VIDEO_PROBE_DURATION"
            ),
        )
