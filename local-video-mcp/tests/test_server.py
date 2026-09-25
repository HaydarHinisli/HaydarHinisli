from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from local_video_mcp import server as server_module
from local_video_mcp.config import Config
from local_video_mcp.player import PlayerError
from local_video_mcp.server import AGE_GATE_MESSAGE, build_server

EXPECTED_TOOLS = {
    "scan_library", "search_videos", "random_video", "get_video", "list_tags",
    "tag_video", "rate_video", "play_video", "library_stats",
}


def call(server, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    result = asyncio.run(server.call_tool(name, arguments or {}))
    assert not result.is_error
    return result.structured_content


def make_server(root: Path, tmp_path: Path, **overrides: Any):
    settings: dict[str, Any] = {
        "library_paths": (root,),
        "db_path": tmp_path / "server.db",
        "age_confirmed": True,
        "probe_duration": False,
    }
    settings.update(overrides)
    return build_server(Config(**settings))


def test_lists_all_tools(root: Path, tmp_path: Path) -> None:
    tools = asyncio.run(make_server(root, tmp_path).list_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


@pytest.mark.parametrize("tool", sorted(EXPECTED_TOOLS))
def test_every_tool_is_locked_without_age_confirmation(root: Path, tmp_path: Path, tool: str) -> None:
    server = make_server(root, tmp_path, age_confirmed=False)
    arguments = {"video_id": 1, "rating": 3} if tool == "rate_video" else {"video_id": 1}
    if tool in {"scan_library", "search_videos", "random_video", "list_tags", "library_stats"}:
        arguments = {}
    with pytest.raises(ToolError, match="adults only"):
        asyncio.run(server.call_tool(tool, arguments))
    assert "18" in AGE_GATE_MESSAGE


def test_missing_library_config_is_explained(tmp_path: Path) -> None:
    server = build_server(Config(library_paths=(), db_path=tmp_path / "x.db", age_confirmed=True))
    with pytest.raises(ToolError, match="VIDEO_LIBRARY_PATHS"):
        asyncio.run(server.call_tool("search_videos", {}))


def test_first_call_scans_automatically(root: Path, tmp_path: Path) -> None:
    server = make_server(root, tmp_path)

    result = call(server, "search_videos", {"tags": ["favoriten"], "sort": "title"})

    assert result["total"] == 2
    assert [video["title"] for video in result["videos"]] == ["Abend", "Strand Urlaub Teil 1"]
    assert set(result["videos"][0]) == {"id", "title", "tags", "duration", "rating"}


def test_tag_rate_and_details(root: Path, tmp_path: Path) -> None:
    server = make_server(root, tmp_path)
    video_id = call(server, "search_videos", {"query": "abend"})["videos"][0]["id"]

    tagged = call(server, "tag_video", {"video_id": video_id, "add": ["Mag ich"], "remove": ["favoriten"]})
    assert tagged["kept_from_files"] == ["favoriten"]
    assert tagged["video"]["tags"] == ["favoriten", "mag ich"]

    assert call(server, "rate_video", {"video_id": video_id, "rating": 5})["rating"] == 5
    details = call(server, "get_video", {"video_id": video_id})
    assert details["rating"] == 5
    assert details["path"] == str(root / "Favoriten" / "Abend.mkv")
    assert call(server, "rate_video", {"video_id": video_id, "rating": None})["rating"] is None


def test_unknown_id_and_invalid_arguments(root: Path, tmp_path: Path) -> None:
    server = make_server(root, tmp_path)
    with pytest.raises(ToolError, match="No video with id 999"):
        asyncio.run(server.call_tool("get_video", {"video_id": 999}))
    with pytest.raises(ToolError, match="No video with id 999"):
        asyncio.run(server.call_tool("tag_video", {"video_id": 999, "add": ["x"]}))
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("rate_video", {"video_id": 1, "rating": 6}))
    with pytest.raises(ToolError):
        asyncio.run(server.call_tool("search_videos", {"limit": 1000}))


def test_random_video_respects_tags(root: Path, tmp_path: Path) -> None:
    server = make_server(root, tmp_path)
    assert call(server, "random_video", {"tags": ["2024"]})["title"] == "Strand Urlaub Teil 1"
    with pytest.raises(ToolError, match="No video matches"):
        asyncio.run(server.call_tool("random_video", {"tags": ["gibt es nicht"]}))


def test_play_video_uses_configured_player(root: Path, tmp_path: Path, monkeypatch) -> None:
    played: list[tuple[Path, str]] = []

    def fake_play(path: Path, player: str) -> str:
        played.append((path, player))
        return "mpv"

    monkeypatch.setattr(server_module, "play", fake_play)
    server = make_server(root, tmp_path, player="mpv --fs")
    video_id = call(server, "search_videos", {"query": "strand"})["videos"][0]["id"]

    assert call(server, "play_video", {"video_id": video_id}) == {
        "playing": "Strand Urlaub Teil 1",
        "player": "mpv",
    }
    assert played == [(root / "Favoriten" / "2024" / "Strand_Urlaub.Teil.1.mp4", "mpv --fs")]


def test_play_video_reports_player_and_file_problems(root: Path, tmp_path: Path, monkeypatch) -> None:
    def broken_play(path: Path, player: str) -> str:
        raise PlayerError("No video player found.")

    monkeypatch.setattr(server_module, "play", broken_play)
    server = make_server(root, tmp_path)
    video_id = call(server, "search_videos", {"query": "strand"})["videos"][0]["id"]
    with pytest.raises(ToolError, match="No video player found"):
        asyncio.run(server.call_tool("play_video", {"video_id": video_id}))

    (root / "Favoriten" / "2024" / "Strand_Urlaub.Teil.1.mp4").unlink()
    with pytest.raises(ToolError, match="no longer exists"):
        asyncio.run(server.call_tool("play_video", {"video_id": video_id}))


def test_play_video_refuses_files_outside_configured_folders(root: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(server_module, "play", lambda path, player: "mpv")
    call(make_server(root, tmp_path), "scan_library")
    # Same index, but the folder was removed from the configuration.
    server = make_server(root / "Serie", tmp_path)
    video_id = next(
        video["id"] for video in call(server, "search_videos", {"limit": 100})["videos"]
        if video["title"] == "Abend"
    )
    with pytest.raises(ToolError, match="no longer inside"):
        asyncio.run(server.call_tool("play_video", {"video_id": video_id}))


def test_scan_and_stats(root: Path, tmp_path: Path) -> None:
    server = make_server(root, tmp_path)

    scan = call(server, "scan_library")
    assert (scan["added"], scan["total"]) == (4, 4)
    stats = call(server, "library_stats")
    assert stats["videos"] == 4
    assert stats["folders"] == [str(root)]
    tags = call(server, "list_tags", {"limit": 1})
    assert tags == {"distinct_tags": 4, "tags": [{"tag": "favoriten", "videos": 2}]}
