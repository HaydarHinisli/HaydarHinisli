"""SQLite-backed index of the videos under the configured library folders.

The index only holds metadata (title, tags, duration, rating). Tags come from
three sources: the folder a video sits in, an optional `<name>.json` sidecar
next to it, and tags the user adds through the assistant. Rescans rewrite the
first two and never touch user tags or ratings.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".wmv", ".flv", ".mpg", ".mpeg", ".ts"}
)

SortOrder = Literal["newest", "oldest", "title", "rating", "longest", "shortest", "random"]

_SORT_SQL: dict[str, str] = {
    "newest": "v.mtime DESC",
    "oldest": "v.mtime ASC",
    "title": "casefold(v.title) ASC",
    "rating": "v.rating IS NULL, v.rating DESC, v.mtime DESC",
    "longest": "v.duration_seconds IS NULL, v.duration_seconds DESC",
    "shortest": "v.duration_seconds IS NULL, v.duration_seconds ASC",
    "random": "RANDOM()",
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sidecar_mtime REAL,
    duration_seconds REAL,
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    added_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tags (
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('folder', 'sidecar', 'user')),
    PRIMARY KEY (video_id, tag, source)
);
CREATE INDEX IF NOT EXISTS tags_by_tag ON tags(tag);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Commit a long scan in chunks so tagging/rating calls are not locked out
# for the whole duration of a large first scan.
_SCAN_COMMIT_EVERY = 200
_MAX_REPORTED_SIDECAR_ERRORS = 20


class VideoNotFound(LookupError):
    pass


def normalize_tag(tag: str) -> str:
    return " ".join(tag.strip().casefold().split())


def normalize_tags(tags: Iterable[str]) -> list[str]:
    return sorted({t for t in (normalize_tag(tag) for tag in tags) if t})


def title_from_filename(path: Path) -> str:
    return " ".join(re.sub(r"[._]+", " ", path.stem).split()) or path.stem


def format_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def is_under(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


@dataclass
class Video:
    id: int
    path: Path
    title: str
    description: str
    size_bytes: int
    mtime: float
    duration_seconds: float | None
    rating: int | None
    tags: list[str]

    def to_summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "tags": self.tags,
            "duration": format_duration(self.duration_seconds),
            "rating": self.rating,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.to_summary(),
            "description": self.description,
            "size_mb": round(self.size_bytes / 1_000_000, 1),
            "modified": datetime.fromtimestamp(self.mtime).date().isoformat(),
            "path": str(self.path),
        }


@dataclass
class ScanResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    total: int = 0
    missing_roots: list[str] = field(default_factory=list)
    sidecar_errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Sidecar:
    title: str | None = None
    description: str = ""
    tags: list[str] = field(default_factory=list)
    mtime: float | None = None
    error: str | None = None


def _read_sidecar(video: Path) -> _Sidecar:
    path = video.with_suffix(".json")
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return _Sidecar()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        title = data.get("title")
        description = data.get("description", "")
        tags = data.get("tags", [])
        if title is not None and not isinstance(title, str):
            raise ValueError("'title' must be a string")
        if not isinstance(description, str):
            raise ValueError("'description' must be a string")
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValueError("'tags' must be a list of strings")
    except (OSError, ValueError) as exc:
        # json.JSONDecodeError and UnicodeDecodeError are ValueErrors.
        return _Sidecar(mtime=mtime, error=f"{path}: {exc}")
    return _Sidecar(
        title=(title or "").strip() or None,
        description=description.strip(),
        tags=normalize_tags(tags),
        mtime=mtime,
    )


def _iter_videos(root: Path) -> Iterator[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        for name in sorted(filenames):
            # Skips dotfiles, including macOS "._name.mp4" resource forks.
            if name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() in VIDEO_EXTENSIONS:
                yield Path(dirpath, name)


def _folder_tags(root: Path, path: Path) -> list[str]:
    return normalize_tags(path.relative_to(root).parts[:-1])


def _probe_duration(ffprobe: str, path: Path) -> float | None:
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
        value = float(out.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return value if value > 0 else None


def _escape_like(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _casefold(value: str | None) -> str | None:
    return value.casefold() if value is not None else None


class Library:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._scan_lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(_SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        # One connection per operation: MCP runs sync tools on worker threads,
        # and sqlite3 connections must not be shared across threads.
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        # SQLite's own LIKE/lower() only fold ASCII; this also handles umlauts.
        conn.create_function("casefold", 1, _casefold, deterministic=True)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def last_scan(self) -> float | None:
        with self._db() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'last_scan'").fetchone()
        return float(row["value"]) if row else None

    def scan(self, roots: Sequence[Path], *, probe_duration: bool = True) -> ScanResult:
        result = ScanResult()
        ffprobe = shutil.which("ffprobe") if probe_duration else None
        with self._scan_lock, self._db() as conn:
            existing = {
                row["path"]: row
                for row in conn.execute("SELECT id, path, size_bytes, mtime, sidecar_mtime FROM videos")
            }
            seen: set[str] = set()
            missing: list[Path] = []
            pending = 0
            for root in roots:
                if not root.is_dir():
                    missing.append(root)
                    continue
                for path in _iter_videos(root):
                    key = str(path)
                    if key in seen:  # overlapping roots
                        continue
                    seen.add(key)
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    sidecar = _read_sidecar(path)
                    if sidecar.error and len(result.sidecar_errors) < _MAX_REPORTED_SIDECAR_ERRORS:
                        result.sidecar_errors.append(sidecar.error)
                    row = existing.get(key)
                    if (
                        row is not None
                        and row["size_bytes"] == stat.st_size
                        and row["mtime"] == stat.st_mtime
                        and row["sidecar_mtime"] == sidecar.mtime
                    ):
                        result.unchanged += 1
                        continue

                    title = sidecar.title or title_from_filename(path)
                    duration = _probe_duration(ffprobe, path) if ffprobe else None
                    if row is None:
                        video_id = conn.execute(
                            "INSERT INTO videos (path, title, description, size_bytes, mtime,"
                            " sidecar_mtime, duration_seconds, added_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (key, title, sidecar.description, stat.st_size, stat.st_mtime,
                             sidecar.mtime, duration, time.time()),
                        ).lastrowid
                        result.added += 1
                    else:
                        video_id = row["id"]
                        conn.execute(
                            "UPDATE videos SET title = ?, description = ?, size_bytes = ?, mtime = ?,"
                            " sidecar_mtime = ?, duration_seconds = ? WHERE id = ?",
                            (title, sidecar.description, stat.st_size, stat.st_mtime,
                             sidecar.mtime, duration, video_id),
                        )
                        conn.execute("DELETE FROM tags WHERE video_id = ? AND source != 'user'", (video_id,))
                        result.updated += 1
                    self._insert_tags(conn, video_id, _folder_tags(root, path), "folder")
                    self._insert_tags(conn, video_id, sidecar.tags, "sidecar")

                    pending += 1
                    if pending >= _SCAN_COMMIT_EVERY:
                        conn.commit()
                        pending = 0

            # Keep entries under a root that is currently unreachable (e.g. an
            # unplugged external drive) so their user tags and ratings survive.
            for key, row in existing.items():
                if key in seen or any(is_under(Path(key), root) for root in missing):
                    continue
                conn.execute("DELETE FROM videos WHERE id = ?", (row["id"],))
                result.removed += 1

            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('last_scan', ?)", (str(time.time()),)
            )
            result.total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
            result.missing_roots = [str(root) for root in missing]
        return result

    @staticmethod
    def _insert_tags(conn: sqlite3.Connection, video_id: int, tags: Iterable[str], source: str) -> None:
        conn.executemany(
            "INSERT OR IGNORE INTO tags (video_id, tag, source) VALUES (?, ?, ?)",
            [(video_id, tag, source) for tag in tags],
        )

    @staticmethod
    def _hydrate(conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]) -> list[Video]:
        if not rows:
            return []
        ids = [row["id"] for row in rows]
        tags: dict[int, set[str]] = {video_id: set() for video_id in ids}
        placeholders = ", ".join("?" * len(ids))
        for tag_row in conn.execute(
            f"SELECT video_id, tag FROM tags WHERE video_id IN ({placeholders})", ids
        ):
            tags[tag_row["video_id"]].add(tag_row["tag"])
        return [
            Video(
                id=row["id"],
                path=Path(row["path"]),
                title=row["title"],
                description=row["description"],
                size_bytes=row["size_bytes"],
                mtime=row["mtime"],
                duration_seconds=row["duration_seconds"],
                rating=row["rating"],
                tags=sorted(tags[row["id"]]),
            )
            for row in rows
        ]

    def get(self, video_id: int) -> Video | None:
        with self._db() as conn:
            row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
            return self._hydrate(conn, [row])[0] if row else None

    def _require(self, conn: sqlite3.Connection, video_id: int) -> None:
        if conn.execute("SELECT 1 FROM videos WHERE id = ?", (video_id,)).fetchone() is None:
            raise VideoNotFound(video_id)

    def search(
        self,
        query: str = "",
        tags: Iterable[str] = (),
        *,
        sort: SortOrder = "newest",
        limit: int = 20,
        offset: int = 0,
        min_rating: int | None = None,
    ) -> tuple[list[Video], int]:
        """Return one page of matching videos and the total number of matches.

        Every word in `query` must appear in the title, description or a tag;
        every entry in `tags` must be an exact tag of the video.
        """
        where: list[str] = []
        params: list[Any] = []
        for term in query.casefold().split():
            like = f"%{_escape_like(term)}%"
            where.append(
                "(casefold(v.title) LIKE ? ESCAPE '\\' OR casefold(v.description) LIKE ? ESCAPE '\\'"
                " OR EXISTS (SELECT 1 FROM tags t WHERE t.video_id = v.id AND t.tag LIKE ? ESCAPE '\\'))"
            )
            params += [like, like, like]
        for tag in normalize_tags(tags):
            where.append("EXISTS (SELECT 1 FROM tags t WHERE t.video_id = v.id AND t.tag = ?)")
            params.append(tag)
        if min_rating is not None:
            where.append("v.rating >= ?")
            params.append(min_rating)
        clause = f"WHERE {' AND '.join(where)}" if where else ""

        with self._db() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM videos v {clause}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT v.* FROM videos v {clause} ORDER BY {_SORT_SQL[sort]}, v.id LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
            return self._hydrate(conn, rows), total

    def list_tags(self) -> list[tuple[str, int]]:
        with self._db() as conn:
            rows = conn.execute(
                "SELECT tag, COUNT(DISTINCT video_id) AS n FROM tags GROUP BY tag ORDER BY n DESC, tag"
            ).fetchall()
        return [(row["tag"], row["n"]) for row in rows]

    def add_tags(self, video_id: int, tags: Iterable[str]) -> None:
        with self._db() as conn:
            self._require(conn, video_id)
            self._insert_tags(conn, video_id, normalize_tags(tags), "user")

    def remove_tags(self, video_id: int, tags: Iterable[str]) -> list[str]:
        """Remove user-added tags. Returns the requested tags that still apply
        because they come from the folder name or the sidecar file."""
        normalized = normalize_tags(tags)
        with self._db() as conn:
            self._require(conn, video_id)
            conn.executemany(
                "DELETE FROM tags WHERE video_id = ? AND tag = ? AND source = 'user'",
                [(video_id, tag) for tag in normalized],
            )
            return [
                tag
                for tag in normalized
                if conn.execute(
                    "SELECT 1 FROM tags WHERE video_id = ? AND tag = ?", (video_id, tag)
                ).fetchone()
            ]

    def set_rating(self, video_id: int, rating: int | None) -> None:
        with self._db() as conn:
            self._require(conn, video_id)
            conn.execute("UPDATE videos SET rating = ? WHERE id = ?", (rating, video_id))

    def stats(self) -> dict[str, Any]:
        with self._db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS videos, COALESCE(SUM(size_bytes), 0) AS size,"
                " SUM(duration_seconds) AS duration, COUNT(rating) AS rated FROM videos"
            ).fetchone()
            tag_count = conn.execute("SELECT COUNT(DISTINCT tag) FROM tags").fetchone()[0]
        last_scan = self.last_scan()
        return {
            "videos": row["videos"],
            "total_size_gb": round(row["size"] / 1_000_000_000, 2),
            "total_duration": format_duration(row["duration"]),
            "rated_videos": row["rated"],
            "distinct_tags": tag_count,
            "last_scan": datetime.fromtimestamp(last_scan).isoformat(timespec="seconds") if last_scan else None,
        }
