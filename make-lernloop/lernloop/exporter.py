"""Export (JSON Lines je Tabelle), Sicherung und Wiederherstellung."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

TABLES = ["meta", "topic", "goal", "open_question", "page_index", "robots", "source", "source_section", "claim",
          "claim_history", "evidence", "conflict", "task", "attempt", "session", "model_call", "fetch_log"]


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def export_jsonl(conn, cfg) -> Path:
    out = cfg.safe_path("exports", f"export-{_stamp()}")
    out.mkdir(parents=True, exist_ok=False)
    for table in TABLES:
        with open(out / f"{table}.jsonl", "w", encoding="utf-8") as f:
            for row in conn.execute(f"SELECT * FROM {table}"):
                f.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
    raw = cfg.safe_path("sources", "raw")
    if raw.exists():
        shutil.copytree(raw, out / "sources_raw")
    return out


def backup(conn, cfg) -> Path:
    target = cfg.safe_path("backups", f"lernloop-{_stamp()}.sqlite")
    target.parent.mkdir(parents=True, exist_ok=True)
    dest = sqlite3.connect(target)
    try:
        conn.backup(dest)  # konsistent, auch während die Datenbank geöffnet ist
    finally:
        dest.close()
    target.with_suffix(".sha256").write_text(file_sha256(target) + "\n")
    return target


def restore(cfg, backup_path: Path) -> Path:
    backup_path = backup_path.resolve()
    checksum = backup_path.with_suffix(".sha256")
    if not checksum.exists():
        raise ValueError(f"Prüfsummendatei fehlt: {checksum}")
    if file_sha256(backup_path) != checksum.read_text().strip():
        raise ValueError("Prüfsumme stimmt nicht – Sicherung beschädigt, Wiederherstellung abgebrochen")
    src = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    try:
        ok = src.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        src.close()
    if ok != "ok":
        raise ValueError(f"Integritätsprüfung fehlgeschlagen: {ok}")
    db = cfg.db_path
    if db.exists():
        keep = cfg.safe_path("backups", f"vor-wiederherstellung-{_stamp()}.sqlite")
        keep.parent.mkdir(parents=True, exist_ok=True)
        live = sqlite3.connect(db)
        dest = sqlite3.connect(keep)
        try:
            live.backup(dest)
        finally:
            dest.close()
            live.close()
        for suffix in ("-wal", "-shm"):
            Path(str(db) + suffix).unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    dest = sqlite3.connect(db)
    try:
        src.backup(dest)
    finally:
        dest.close()
        src.close()
    return db
