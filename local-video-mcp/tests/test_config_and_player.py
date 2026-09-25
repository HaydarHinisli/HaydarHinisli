from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from local_video_mcp import player
from local_video_mcp.config import Config
from local_video_mcp.player import PlayerError, play


def test_config_defaults_to_locked(tmp_path: Path) -> None:
    config = Config.from_env({"XDG_DATA_HOME": str(tmp_path)})
    assert config.age_confirmed is False
    assert config.library_paths == ()
    assert config.player == "auto"
    assert config.probe_duration is True
    if os.name != "nt":
        assert config.db_path == tmp_path / "local-video-mcp" / "library.db"


def test_config_from_env(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    config = Config.from_env({
        "VIDEO_LIBRARY_PATHS": f"{a}{os.pathsep}{os.pathsep}{b}",
        "VIDEO_DB_PATH": str(tmp_path / "db.sqlite"),
        "VIDEO_PLAYER": "vlc --fullscreen",
        "VIDEO_AGE_CONFIRMED": "Ja",
        "VIDEO_PROBE_DURATION": "false",
    })
    assert config.library_paths == (a.resolve(), b.resolve())
    assert config.db_path == tmp_path / "db.sqlite"
    assert config.player == "vlc --fullscreen"
    assert config.age_confirmed is True
    assert config.probe_duration is False


def test_config_rejects_unclear_booleans() -> None:
    with pytest.raises(ValueError, match="VIDEO_AGE_CONFIRMED"):
        Config.from_env({"VIDEO_AGE_CONFIRMED": "vielleicht"})


class FakePopen:
    calls: list[tuple[list[str], dict]] = []

    def __init__(self, command: list[str], **kwargs) -> None:
        FakePopen.calls.append((command, kwargs))


@pytest.fixture
def fake_popen(monkeypatch):
    FakePopen.calls = []
    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    return FakePopen


def test_custom_player_command_is_split_and_detached(fake_popen, tmp_path: Path) -> None:
    video = tmp_path / "my clip.mp4"

    assert play(video, "mpv --fs") == "mpv"

    command, kwargs = fake_popen.calls[0]
    assert command == ["mpv", "--fs", str(video)]
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stdin"] is subprocess.DEVNULL


def test_auto_prefers_mpv_then_vlc(fake_popen, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(player.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "vlc" else None)
    assert play(tmp_path / "a.mp4") == "vlc"
    assert fake_popen.calls[0][0][0] == "/usr/bin/vlc"


def test_auto_without_any_player_fails_clearly(fake_popen, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(player.sys, "platform", "linux")
    monkeypatch.setattr(player.shutil, "which", lambda name: None)
    with pytest.raises(PlayerError, match="Install mpv or VLC"):
        play(tmp_path / "a.mp4")


def test_missing_custom_player_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(PlayerError, match="Could not start"):
        play(tmp_path / "a.mp4", "definitely-not-a-real-player-binary")
