"""SQLite-Wissensspeicher: Schema, Verbindungen, IDs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

_TOKENIZE = "tokenize='unicode61 remove_diacritics 2'"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS topic (
    id TEXT PRIMARY KEY,
    parent_id TEXT,
    title TEXT NOT NULL,
    description TEXT,
    prerequisites TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'offen'
);

-- status: offen | in_arbeit | beantwortet | teilweise | ungeklärt
CREATE TABLE IF NOT EXISTS goal (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES topic(id),
    ord INTEGER NOT NULL,
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offen',
    status_reason TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS open_question (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES goal(id),
    text TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offen',
    session_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS page_index (
    url TEXT PRIMARY KEY,
    host TEXT NOT NULL,
    title TEXT,
    lastmod TEXT,
    discovered_via TEXT,
    discovered_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS page_index_fts USING fts5(url UNINDEXED, title, words, {_TOKENIZE});

CREATE TABLE IF NOT EXISTS robots (
    host TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    status INTEGER,
    body TEXT
);

CREATE TABLE IF NOT EXISTS source (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    final_url TEXT NOT NULL,
    title TEXT,
    fetched_at TEXT NOT NULL,
    published_or_updated_at TEXT,
    version_ref TEXT,
    content_hash TEXT NOT NULL,
    raw_path TEXT,
    source_type TEXT NOT NULL DEFAULT 'offizielle_doku',
    session_id TEXT
);

CREATE TABLE IF NOT EXISTS source_section (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES source(id),
    ord INTEGER NOT NULL,
    anchor TEXT,
    heading_path TEXT,
    text TEXT NOT NULL,
    content_hash TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS section_fts USING fts5(section_id UNINDEXED, heading_path, text, {_TOKENIZE});

CREATE TABLE IF NOT EXISTS claim (
    id TEXT PRIMARY KEY,
    topic_id TEXT,
    goal_id TEXT,
    statement TEXT NOT NULL,
    keywords TEXT,
    app TEXT,
    module TEXT,
    module_version TEXT,
    scope TEXT,
    preconditions TEXT,
    io_behavior TEXT,
    derivation TEXT NOT NULL,
    status TEXT NOT NULL,
    status_reason TEXT NOT NULL,
    last_reviewed_at TEXT,
    reviewed_by TEXT,
    supersedes_id TEXT,
    session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS claim_fts USING fts5(claim_id UNINDEXED, statement, keywords, module, scope, {_TOKENIZE});

CREATE TABLE IF NOT EXISTS claim_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    change TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    reason TEXT,
    actor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claim(id),
    section_id TEXT NOT NULL REFERENCES source_section(id),
    quote TEXT NOT NULL,
    relation TEXT NOT NULL,
    verified_quote INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS conflict (
    id TEXT PRIMARY KEY,
    claim_ids TEXT NOT NULL,
    kind TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offen',
    resolution TEXT,
    session_id TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

-- pool: übung | prüfung | ausgemustert
CREATE TABLE IF NOT EXISTS task (
    id TEXT PRIMARY KEY,
    pool TEXT NOT NULL,
    topic_id TEXT,
    task_type TEXT NOT NULL,
    prompt TEXT NOT NULL,
    expected TEXT NOT NULL,
    rubric TEXT,
    expected_source TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attempt (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES task(id),
    session_id TEXT,
    variant TEXT NOT NULL,
    answer TEXT NOT NULL,
    cited_claims TEXT NOT NULL DEFAULT '[]',
    grade_status TEXT NOT NULL DEFAULT 'offen',
    passed INTEGER,
    grader TEXT,
    grade_note TEXT,
    error_class TEXT,
    created_at TEXT NOT NULL
);

-- state: siehe session.py; end_reason: ziel_erreicht | limit_erreicht | beweislage_fehlt |
--        kein_fortschritt | abgebrochen_durch_nutzer | absturz_erkannt
CREATE TABLE IF NOT EXISTS session (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    state TEXT NOT NULL,
    paused_reason TEXT,
    end_reason TEXT,
    end_detail TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    active_seconds REAL NOT NULL DEFAULT 0,
    limits_snapshot TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '{{}}'
);

CREATE TABLE IF NOT EXISTS model_call (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    step TEXT NOT NULL,
    backend TEXT NOT NULL,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cost_usd_equiv REAL,
    duration_ms INTEGER,
    ok INTEGER NOT NULL,
    error TEXT,
    log_path TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    url TEXT NOT NULL,
    status INTEGER,
    bytes INTEGER,
    error TEXT,
    created_at TEXT NOT NULL
);
"""

ID_PREFIX = {
    "claim": "ERK",
    "evidence": "BEL",
    "source": "QUE",
    "source_section": "ABS",
    "conflict": "KON",
    "task": "AUF",
    "attempt": "VER",
    "session": "SIT",
    "model_call": "MOD",
    "open_question": "FRA",
    "goal": "ZIEL",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, isolation_level=None)
    else:
        conn = sqlite3.connect(path, isolation_level=None, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),)
    )


def new_id(conn: sqlite3.Connection, kind: str) -> str:
    prefix = ID_PREFIX[kind]
    key = f"seq:{prefix}"
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    n = int(row["value"]) + 1 if row else 1
    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, str(n)))
    return f"{prefix}-{n:06d}"


class Tx:
    """Explizite Transaktion (BEGIN IMMEDIATE … COMMIT/ROLLBACK)."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def __enter__(self) -> sqlite3.Connection:
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")


def fts_query(text: str) -> str:
    """Freitext in eine sichere FTS5-Abfrage (ODER-verknüpfte Wörter) umwandeln."""
    words = []
    for raw in text.replace("-", " ").replace("_", " ").split():
        w = "".join(ch for ch in raw if ch.isalnum())
        if len(w) >= 2 and w.lower() not in _STOP:
            words.append(f'"{w}"')
    return " OR ".join(dict.fromkeys(words))


_STOP = {
    "the", "and", "or", "of", "to", "in", "is", "a", "an", "for", "on", "with", "how", "what",
    "der", "die", "das", "und", "oder", "ist", "ein", "eine", "wie", "was", "bei", "mit", "von",
    "im", "in", "zu", "den", "dem", "des", "wird", "werden", "nicht",
}
