"""MCP server exposing the local video library as tools."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__
from .config import Config
from .library import Library, SortOrder, Video, VideoNotFound, is_under
from .player import PlayerError, play

AGE_GATE_MESSAGE = (
    "Access is locked. This library is for adults only: the user has to confirm they are 18 or "
    "older by setting VIDEO_AGE_CONFIRMED=true in this server's configuration and restarting it."
)
NO_LIBRARY_MESSAGE = (
    "No library folder is configured. Set VIDEO_LIBRARY_PATHS in this server's configuration "
    "to one or more folders (separated by ':' on Linux/macOS, ';' on Windows)."
)

INSTRUCTIONS = """\
Tools for the user's private video library on this computer. Only metadata is
available (title, tags, duration, rating, description from the user's own
sidecar files); you cannot see the videos themselves, so never describe or
invent their content. Find videos with search_videos or random_video, then use
the returned id with get_video, play_video, tag_video or rate_video. Run
scan_library when the user says files were added, moved or deleted.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=False)
UPDATES_INDEX = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)
STARTS_PLAYER = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)

VideoId = Annotated[int, Field(description="Video id as returned by search_videos.")]
TagList = Annotated[list[str], Field(description="Tags; matching ignores case.")]


def build_server(config: Config, library: Library | None = None) -> MCPServer:
    library = library or Library(config.db_path)
    server = MCPServer(name="local-video-library", instructions=INSTRUCTIONS, version=__version__)

    def check_access() -> None:
        if not config.age_confirmed:
            raise ToolError(AGE_GATE_MESSAGE)
        if not config.library_paths:
            raise ToolError(NO_LIBRARY_MESSAGE)

    def ready() -> Library:
        check_access()
        if library.last_scan() is None:
            library.scan(config.library_paths, probe_duration=config.probe_duration)
        return library

    def lookup(video_id: int) -> Video:
        video = ready().get(video_id)
        if video is None:
            raise ToolError(f"No video with id {video_id}. Use search_videos to find valid ids.")
        return video

    @server.tool(annotations=UPDATES_INDEX)
    def scan_library() -> dict[str, Any]:
        """Re-index the library folders. Run after files were added, renamed, moved or deleted."""
        check_access()
        return library.scan(config.library_paths, probe_duration=config.probe_duration).to_dict()

    @server.tool(annotations=READ_ONLY)
    def search_videos(
        query: Annotated[
            str,
            Field(description="Words that must all appear in title, description or tags. Empty matches everything."),
        ] = "",
        tags: Annotated[list[str] | None, Field(description="Only videos that have ALL of these tags.")] = None,
        sort: SortOrder = "newest",
        limit: Annotated[int, Field(ge=1, le=100)] = 20,
        offset: Annotated[int, Field(ge=0, description="Skip this many results, for paging.")] = 0,
        min_rating: Annotated[int | None, Field(ge=1, le=5)] = None,
    ) -> dict[str, Any]:
        """Search the library. Returns one page of results and the total number of matches."""
        videos, total = ready().search(
            query, tags or (), sort=sort, limit=limit, offset=offset, min_rating=min_rating
        )
        return {"total": total, "offset": offset, "videos": [video.to_summary() for video in videos]}

    @server.tool(annotations=READ_ONLY)
    def random_video(
        tags: Annotated[
            list[str] | None, Field(description="Pick only among videos that have ALL of these tags.")
        ] = None,
    ) -> dict[str, Any]:
        """Pick one random video, optionally restricted to some tags."""
        videos, _ = ready().search(tags=tags or (), sort="random", limit=1)
        if not videos:
            raise ToolError("No video matches these tags.")
        return videos[0].to_dict()

    @server.tool(annotations=READ_ONLY)
    def get_video(video_id: VideoId) -> dict[str, Any]:
        """Full details of one video: tags, duration, size, rating, description and file path."""
        return lookup(video_id).to_dict()

    @server.tool(annotations=READ_ONLY)
    def list_tags(limit: Annotated[int, Field(ge=1, le=1000)] = 200) -> dict[str, Any]:
        """All tags in the library with how many videos have each, most used first."""
        tags = ready().list_tags()
        return {
            "distinct_tags": len(tags),
            "tags": [{"tag": tag, "videos": count} for tag, count in tags[:limit]],
        }

    @server.tool(annotations=UPDATES_INDEX)
    def tag_video(
        video_id: VideoId,
        add: TagList | None = None,
        remove: TagList | None = None,
    ) -> dict[str, Any]:
        """Add or remove the user's own tags on a video.

        Tags that come from the folder name or a sidecar .json file cannot be
        removed here; they are reported under `kept_from_files`.
        """
        lib = ready()
        try:
            if add:
                lib.add_tags(video_id, add)
            kept = lib.remove_tags(video_id, remove) if remove else []
        except VideoNotFound:
            raise ToolError(f"No video with id {video_id}.") from None
        return {"video": lookup(video_id).to_summary(), "kept_from_files": kept}

    @server.tool(annotations=UPDATES_INDEX)
    def rate_video(
        video_id: VideoId,
        rating: Annotated[int | None, Field(ge=1, le=5, description="1-5 stars, or null to clear.")],
    ) -> dict[str, Any]:
        """Set or clear the user's star rating for a video."""
        try:
            ready().set_rating(video_id, rating)
        except VideoNotFound:
            raise ToolError(f"No video with id {video_id}.") from None
        return lookup(video_id).to_summary()

    @server.tool(annotations=STARTS_PLAYER)
    def play_video(video_id: VideoId) -> dict[str, Any]:
        """Open a video in the video player on the user's computer."""
        video = lookup(video_id)
        if not any(is_under(video.path, root) for root in config.library_paths):
            raise ToolError("This video is no longer inside a configured library folder. Run scan_library.")
        if not video.path.is_file():
            raise ToolError("The file no longer exists. Run scan_library to refresh the index.")
        try:
            player = play(video.path, config.player)
        except PlayerError as exc:
            raise ToolError(str(exc)) from exc
        return {"playing": video.title, "player": player}

    @server.tool(annotations=READ_ONLY)
    def library_stats() -> dict[str, Any]:
        """Size of the library: number of videos, total size and duration, tags, last scan time."""
        return {**ready().stats(), "folders": [str(root) for root in config.library_paths]}

    return server
