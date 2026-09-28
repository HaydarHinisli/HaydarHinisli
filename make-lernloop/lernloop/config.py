"""Konfiguration laden und Pfade auf das Projektverzeichnis begrenzen."""

from __future__ import annotations

import copy
try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    from . import _toml as tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULTS: dict = {
    "model": {
        "backend": "claude_code",
        "claude_code_model": "opus",
        "claude_code_command": "claude",
        "call_timeout_seconds": 600,
        "claude_code_json_schema": True,
    },
    "subscription_limits": {"max_calls_per_day": 60},
    "api": {"paid_calls_enabled": False, "model_id": "claude-opus-5", "total_budget_usd": 0.0},
    "session": {
        "max_duration_minutes": 30,
        "max_model_calls": 25,
        "max_page_fetches": 40,
        "max_rounds": 4,
        "max_rounds_without_progress": 2,
        "max_pages_per_round": 3,
        "max_chars_per_page": 14000,
    },
    "fetch": {
        "terms_reviewed": False,
        "store_raw_html": False,
        "allowed_hosts": ["help.make.com", "developers.make.com", "apps.make.com"],
        "allowed_path_prefixes": {},
        "max_redirects": 3,
        "max_page_bytes": 2_000_000,
        "timeout_seconds": 20,
        "min_seconds_between_requests_per_host": 2.0,
        "user_agent": "make-lernloop/0.1 (lokales Lernprojekt; manuell gestartet)",
    },
    "paths": {"data_dir": "./data"},
}

CONFIG_FILENAME = "lernloop.toml"


class ConfigError(Exception):
    pass


class PathOutsideProject(Exception):
    pass


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass
class Config:
    raw: dict
    base_dir: Path

    @property
    def data_dir(self) -> Path:
        return (self.base_dir / self.raw["paths"]["data_dir"]).resolve()

    @property
    def db_path(self) -> Path:
        return self.data_dir / "lernloop.sqlite"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / "lernloop.lock"

    def section(self, name: str) -> dict:
        return self.raw[name]

    def safe_path(self, *parts: str) -> Path:
        """Pfad innerhalb von data_dir; alles andere wird abgewiesen."""
        root = self.data_dir
        candidate = root.joinpath(*parts).resolve()
        if candidate != root and root not in candidate.parents:
            raise PathOutsideProject(f"Pfad liegt außerhalb des Projektbereichs: {candidate}")
        return candidate


def load_config(path: Path | None = None) -> Config:
    if path is None:
        path = Path.cwd() / CONFIG_FILENAME
    path = path.resolve()
    if path.exists():
        with open(path, "rb") as f:
            try:
                user = tomllib.load(f)
            except tomllib.TOMLDecodeError as exc:
                raise ConfigError(f"{path}: {exc}") from exc
        raw = _merge(DEFAULTS, user)
    else:
        raw = copy.deepcopy(DEFAULTS)
    cfg = Config(raw=raw, base_dir=path.parent)
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    backend = cfg.raw["model"]["backend"]
    if backend not in ("claude_code", "anthropic_api", "fake"):
        raise ConfigError(f"Unbekanntes model.backend: {backend}")
    for key, value in cfg.raw["session"].items():
        if not isinstance(value, (int, float)) or value <= 0:
            raise ConfigError(f"session.{key} muss eine positive Zahl sein")
