from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from local_video_mcp.library import Library, VideoNotFound, format_duration, title_from_filename

from .conftest import make_sidecar, make_video


def titles(videos) -> list[str]:
    return [video.title for video in videos]


def by_title(library: Library, title: str):
    videos, _ = library.search(limit=100)
    return next(video for video in videos if video.title == title)


def test_first_scan_indexes_videos_only(library: Library, root: Path) -> None:
    result = library.scan([root], probe_duration=False)

    assert (result.added, result.updated, result.removed, result.total) == (4, 0, 0, 4)
    assert library.last_scan() is not None
    videos, total = library.search(sort="title", limit=100)
    assert total == 4
    assert titles(videos) == ["Abend", "Große Folge", "Strand Urlaub Teil 1", "Übersicht"]


def test_folder_and_sidecar_metadata(library: Library, root: Path) -> None:
    library.scan([root], probe_duration=False)

    assert by_title(library, "Strand Urlaub Teil 1").tags == ["2024", "favoriten"]
    assert by_title(library, "Übersicht").tags == []
    episode = by_title(library, "Große Folge")
    assert episode.description == "Zweiter Teil"
    assert episode.tags == ["lang", "serie"]  # folder "Serie" and sidecar " Serie " merge


def test_rescan_detects_unchanged_updated_and_removed(library: Library, root: Path) -> None:
    library.scan([root], probe_duration=False)
    abend = by_title(library, "Abend")
    library.add_tags(abend.id, ["Mag ich"])
    library.set_rating(abend.id, 4)

    result = library.scan([root], probe_duration=False)
    assert (result.added, result.updated, result.removed, result.unchanged) == (0, 0, 0, 4)

    make_video(root / "Favoriten" / "Abend.mkv", b"longer content now")
    (root / "Übersicht.webm").unlink()
    make_video(root / "Neu.mp4")
    result = library.scan([root], probe_duration=False)

    assert (result.added, result.updated, result.removed, result.unchanged) == (1, 1, 1, 2)
    updated = library.get(abend.id)
    assert updated is not None
    assert updated.rating == 4
    assert updated.tags == ["favoriten", "mag ich"]


def test_sidecar_change_triggers_update(library: Library, root: Path) -> None:
    library.scan([root], probe_duration=False)
    video = root / "Serie" / "folge-02.mp4"
    sidecar = make_sidecar(video, {"title": "Neuer Titel", "tags": ["kurz"]})
    stat = sidecar.stat()
    # Make sure the mtime differs even on filesystems with coarse timestamps.
    os.utime(sidecar, (stat.st_atime, stat.st_mtime + 10))

    result = library.scan([root], probe_duration=False)

    assert result.updated == 1
    assert by_title(library, "Neuer Titel").tags == ["kurz", "serie"]


def test_invalid_sidecar_is_reported_but_video_indexed(library: Library, tmp_path: Path) -> None:
    root = tmp_path / "lib"
    video = make_video(root / "clip.mp4")
    make_sidecar(video, "{not json")
    other = make_video(root / "other.mp4")
    make_sidecar(other, {"tags": "not-a-list"})

    result = library.scan([root], probe_duration=False)

    assert result.added == 2
    assert len(result.sidecar_errors) == 2
    assert titles(library.search(sort="title")[0]) == ["clip", "other"]


def test_unreachable_root_keeps_its_entries(library: Library, root: Path, tmp_path: Path) -> None:
    second = tmp_path / "external"
    make_video(second / "extern.mp4")
    library.scan([root, second], probe_duration=False)
    extern = by_title(library, "extern")
    library.set_rating(extern.id, 5)

    shutil.rmtree(second)
    result = library.scan([root, second], probe_duration=False)

    assert result.removed == 0
    assert result.missing_roots == [str(second)]
    kept = library.get(extern.id)
    assert kept is not None and kept.rating == 5


def test_removed_root_drops_its_entries(library: Library, root: Path, tmp_path: Path) -> None:
    second = tmp_path / "other"
    make_video(second / "a.mp4")
    library.scan([root, second], probe_duration=False)

    result = library.scan([root], probe_duration=False)

    assert result.removed == 1
    assert result.total == 4


def test_search_query_is_case_insensitive_including_umlauts(library: Library, root: Path) -> None:
    library.scan([root], probe_duration=False)

    assert titles(library.search("übersicht")[0]) == ["Übersicht"]
    assert titles(library.search("GROSSE folge")[0]) == ["Große Folge"]  # "ß" casefolds to "ss"
    assert titles(library.search("zweiter")[0]) == ["Große Folge"]  # description
    assert set(titles(library.search("favo")[0])) == {"Abend", "Strand Urlaub Teil 1"}  # tag substring


def test_search_tags_must_all_match(library: Library, root: Path) -> None:
    library.scan([root], probe_duration=False)

    assert set(titles(library.search(tags=["Favoriten"])[0])) == {"Abend", "Strand Urlaub Teil 1"}
    assert titles(library.search(tags=["favoriten", "2024"])[0]) == ["Strand Urlaub Teil 1"]
    assert library.search(tags=["favoriten", "serie"]) == ([], 0)


def test_search_like_wildcards_are_literal(library: Library, tmp_path: Path) -> None:
    root = tmp_path / "lib"
    make_video(root / "100% echt.mp4")
    make_video(root / "anderes.mp4")
    library.scan([root], probe_duration=False)

    assert titles(library.search("%")[0]) == ["100% echt"]


def test_search_sorting_paging_and_rating(library: Library, root: Path) -> None:
    library.scan([root], probe_duration=False)

    newest, total = library.search(sort="newest", limit=2)
    assert total == 4
    assert titles(newest) == ["Strand Urlaub Teil 1", "Abend"]
    assert titles(library.search(sort="newest", limit=2, offset=2)[0]) == ["Übersicht", "Große Folge"]
    assert titles(library.search(sort="oldest", limit=1)[0]) == ["Große Folge"]

    library.set_rating(by_title(library, "Abend").id, 3)
    library.set_rating(by_title(library, "Übersicht").id, 5)
    assert titles(library.search(sort="rating", limit=2)[0]) == ["Übersicht", "Abend"]
    assert titles(library.search(min_rating=4)[0]) == ["Übersicht"]


def test_remove_tags_only_removes_user_tags(library: Library, root: Path) -> None:
    library.scan([root], probe_duration=False)
    video = by_title(library, "Abend")
    library.add_tags(video.id, ["Abends", "  Kurz  "])

    kept = library.remove_tags(video.id, ["kurz", "FAVORITEN"])

    assert kept == ["favoriten"]
    assert library.get(video.id).tags == ["abends", "favoriten"]


def test_unknown_video_raises(library: Library) -> None:
    with pytest.raises(VideoNotFound):
        library.add_tags(42, ["x"])
    with pytest.raises(VideoNotFound):
        library.set_rating(42, 3)
    assert library.get(42) is None


def test_list_tags_and_stats(library: Library, root: Path) -> None:
    library.scan([root], probe_duration=False)

    tags = dict(library.list_tags())
    assert tags == {"favoriten": 2, "2024": 1, "serie": 1, "lang": 1}
    stats = library.stats()
    assert stats["videos"] == 4
    assert stats["distinct_tags"] == 4
    assert stats["total_duration"] is None


def test_helpers() -> None:
    assert title_from_filename(Path("My_clip.part.2.mp4")) == "My clip part 2"
    assert format_duration(None) is None
    assert format_duration(59.6) == "1:00"
    assert format_duration(3725) == "1:02:05"


@pytest.mark.skipif(os.name == "nt", reason="uses a shell script as a stand-in for ffprobe")
def test_duration_comes_from_ffprobe(library: Library, tmp_path: Path, monkeypatch) -> None:
    fake = tmp_path / "bin" / "ffprobe"
    fake.parent.mkdir()
    fake.write_text('#!/bin/sh\ncase "$*" in *broken*) echo N/A ;; *) echo 3725.4 ;; esac\n')
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake.parent))
    root = tmp_path / "lib"
    make_video(root / "long.mp4")
    make_video(root / "broken.mp4")

    library.scan([root], probe_duration=True)

    assert library.search("long")[0][0].to_summary()["duration"] == "1:02:05"
    assert library.search("broken")[0][0].duration_seconds is None
    assert library.stats()["total_duration"] == "1:02:05"
