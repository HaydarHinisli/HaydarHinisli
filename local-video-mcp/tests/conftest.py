from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from local_video_mcp.library import Library


def make_video(path: Path, content: bytes = b"video", *, mtime: float | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def make_sidecar(video: Path, data: object) -> Path:
    sidecar = video.with_suffix(".json")
    sidecar.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return sidecar


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / "videos"
    make_video(root / "Favoriten" / "2024" / "Strand_Urlaub.Teil.1.mp4", mtime=1_700_000_300)
    make_video(root / "Favoriten" / "Abend.mkv", mtime=1_700_000_200)
    make_video(root / "Übersicht.webm", mtime=1_700_000_100)
    beach = make_video(root / "Serie" / "folge-02.mp4", mtime=1_700_000_000)
    make_sidecar(beach, {"title": "Große Folge", "description": "Zweiter Teil", "tags": ["Lang", " Serie "]})
    # Ignored: not a video, hidden files and hidden folders.
    (root / "notes.txt").write_text("x")
    make_video(root / "._Abend.mkv")
    make_video(root / ".cache" / "thumb.mp4")
    return root


@pytest.fixture
def library(tmp_path: Path) -> Library:
    return Library(tmp_path / "index" / "library.db")
