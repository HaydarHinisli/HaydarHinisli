"""Wissensspeicher: Quellen, Erkenntnisse, Belege, Konflikte – mit programmseitigen Statusregeln."""

from __future__ import annotations

import hashlib
import json

from . import db as dbm
from .extract import Page, quote_in_text

# Status, die beim Wissensabruf als aktueller Stand geliefert werden.
CURRENT_STATUSES = ("dokumentiert", "theoretisch_geprüft", "widersprüchlich", "ungeklärt")
ALL_STATUSES = ("entwurf", "dokumentiert", "theoretisch_geprüft", "praktisch_bestätigt",
                "widersprüchlich", "veraltet", "zurückgezogen", "ungeklärt")


class StatusRuleViolation(Exception):
    pass


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- Quellen ---------------------------------------------------------------------------------

def store_page(conn, cfg, fetch_result, page: Page, session_id: str | None) -> tuple[str, bool]:
    """Speichert eine abgerufene Seite. Liefert (source_id, neu_oder_geändert)."""
    content_hash = sha("\n\n".join(s.text for s in page.sections))
    same = conn.execute(
        "SELECT id FROM source WHERE final_url=? AND content_hash=? ORDER BY fetched_at DESC LIMIT 1",
        (fetch_result.final_url, content_hash),
    ).fetchone()
    if same:
        return same["id"], False
    previous = conn.execute(
        "SELECT id FROM source WHERE final_url=? ORDER BY fetched_at DESC LIMIT 1", (fetch_result.final_url,)
    ).fetchone()
    raw_path = None
    if cfg.section("fetch").get("store_raw_html"):
        path = cfg.safe_path("sources", "raw", f"{sha(fetch_result.text)[:32]}.html")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fetch_result.text, encoding="utf-8")
        raw_path = str(path.relative_to(cfg.data_dir))
    source_id = dbm.new_id(conn, "source")
    conn.execute(
        "INSERT INTO source(id, url, final_url, title, fetched_at, published_or_updated_at, version_ref, "
        "content_hash, raw_path, source_type, session_id) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (source_id, fetch_result.url, fetch_result.final_url, page.title, dbm.now(), page.updated_at, None,
         content_hash, raw_path, "offizielle_doku", session_id),
    )
    for i, s in enumerate(page.sections):
        sid = dbm.new_id(conn, "source_section")
        conn.execute(
            "INSERT INTO source_section(id, source_id, ord, anchor, heading_path, text, content_hash) "
            "VALUES(?,?,?,?,?,?,?)",
            (sid, source_id, i, s.anchor, s.heading_path, s.text, sha(s.text)),
        )
        conn.execute("INSERT INTO section_fts(section_id, heading_path, text) VALUES(?,?,?)",
                     (sid, s.heading_path, s.text))
    if previous:
        mark_stale_claims(conn, previous["id"], source_id)
    return source_id, True


def mark_stale_claims(conn, old_source_id: str, new_source_id: str) -> list[str]:
    """Belege aus einer älteren Fassung, deren Zitat in der neuen Fassung fehlt → Erkenntnis veraltet."""
    new_text = "\n".join(r["text"] for r in conn.execute(
        "SELECT text FROM source_section WHERE source_id=?", (new_source_id,)))
    stale = []
    rows = conn.execute(
        "SELECT DISTINCT e.claim_id, e.quote, c.status FROM evidence e JOIN source_section s ON s.id=e.section_id "
        "JOIN claim c ON c.id=e.claim_id WHERE s.source_id=? AND e.relation='stützt'", (old_source_id,)
    ).fetchall()
    for r in rows:
        if r["status"] in ("zurückgezogen", "veraltet"):
            continue
        if not quote_in_text(r["quote"], new_text):
            set_status(conn, r["claim_id"], "veraltet",
                       f"Zitat nicht mehr in aktueller Fassung der Quelle ({new_source_id})", "programm")
            stale.append(r["claim_id"])
    return stale


def sections_of(conn, source_id: str):
    return conn.execute("SELECT * FROM source_section WHERE source_id=? ORDER BY ord", (source_id,)).fetchall()


# --- Erkenntnisse ------------------------------------------------------------------------------

def add_claim(conn, session_id: str, topic_id: str, goal_id: str, item: dict,
              allowed_section_ids: set[str]) -> tuple[str, bool]:
    """Legt eine Erkenntnis als Entwurf an. Liefert (claim_id, zitat_verifiziert)."""
    section_id = item.get("abschnitt_id", "")
    verified = False
    if section_id in allowed_section_ids:
        row = conn.execute("SELECT text FROM source_section WHERE id=?", (section_id,)).fetchone()
        verified = bool(row) and quote_in_text(item.get("zitat", ""), row["text"])
    reason = "Neu erfasst; Zitat wörtlich in der Quelle gefunden" if verified else \
        "Neu erfasst; Zitat NICHT wörtlich im angegebenen Abschnitt gefunden"
    cid = dbm.new_id(conn, "claim")
    ts = dbm.now()
    conn.execute(
        "INSERT INTO claim(id, topic_id, goal_id, statement, keywords, app, module, module_version, scope, "
        "preconditions, io_behavior, derivation, status, status_reason, session_id, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, topic_id, goal_id, item["aussage"].strip(), item.get("schlagworte_en"), _opt(item.get("app")),
         _opt(item.get("modul")), _opt(item.get("modulversion")), item.get("geltungsbereich"),
         item.get("voraussetzungen"), item.get("ein_ausgabe"), item["ableitung"], "entwurf", reason,
         session_id, ts, ts),
    )
    conn.execute("INSERT INTO claim_fts(claim_id, statement, keywords, module, scope) VALUES(?,?,?,?,?)",
                 (cid, item["aussage"], item.get("schlagworte_en") or "", item.get("modul") or "",
                  item.get("geltungsbereich") or ""))
    _history(conn, cid, "angelegt", None, "entwurf", reason, "programm")
    if section_id in allowed_section_ids:
        conn.execute(
            "INSERT INTO evidence(id, claim_id, section_id, quote, relation, verified_quote) VALUES(?,?,?,?,?,?)",
            (dbm.new_id(conn, "evidence"), cid, section_id, item.get("zitat", ""), "stützt", int(verified)),
        )
    return cid, verified


def _opt(v):
    v = (v or "").strip()
    return v or None


def _history(conn, claim_id, change, old, new, reason, actor):
    conn.execute(
        "INSERT INTO claim_history(claim_id, changed_at, change, old_status, new_status, reason, actor) "
        "VALUES(?,?,?,?,?,?,?)", (claim_id, dbm.now(), change, old, new, reason, actor))


def set_status(conn, claim_id: str, new_status: str, reason: str, actor: str) -> None:
    """Einziger Weg, einen Status zu ändern. Regeln werden hier geprüft."""
    if new_status not in ALL_STATUSES:
        raise StatusRuleViolation(f"Unbekannter Status {new_status}")
    if not reason or not reason.strip():
        raise StatusRuleViolation("Statuswechsel ohne Begründung ist nicht erlaubt")
    claim = conn.execute("SELECT * FROM claim WHERE id=?", (claim_id,)).fetchone()
    if not claim:
        raise StatusRuleViolation(f"Erkenntnis {claim_id} existiert nicht")
    old = claim["status"]
    if old == new_status:
        return
    if new_status == "praktisch_bestätigt":
        raise StatusRuleViolation("„praktisch bestätigt“ ist in Version 1 gesperrt (keine Experimente, Brief §10)")
    if new_status == "dokumentiert":
        _require_documented(conn, claim, actor)
    if new_status == "theoretisch_geprüft":
        if old != "dokumentiert":
            raise StatusRuleViolation("„theoretisch geprüft“ setzt „dokumentiert“ voraus")
        passed = conn.execute(
            "SELECT COUNT(*) FROM attempt a JOIN task t ON t.id=a.task_id WHERE a.passed=1 AND a.grade_status='bewertet' "
            "AND t.pool='übung' AND t.expected_source IN ('mensch','experiment') AND a.cited_claims LIKE ?",
            (f'%"{claim_id}"%',)).fetchone()[0]
        if not passed:
            raise StatusRuleViolation("Keine bestandene, fachlich bewertete Übung stützt diese Erkenntnis")
    if old == "zurückgezogen" and actor != "mensch":
        raise StatusRuleViolation("Zurückgezogene Erkenntnisse kann nur ein Mensch reaktivieren")
    reviewed = actor if actor == "mensch" else claim["reviewed_by"]
    conn.execute(
        "UPDATE claim SET status=?, status_reason=?, updated_at=?, last_reviewed_at=?, reviewed_by=? WHERE id=?",
        (new_status, reason, dbm.now(), dbm.now(), reviewed, claim_id))
    _history(conn, claim_id, "status", old, new_status, reason, actor)


def _require_documented(conn, claim, actor: str) -> None:
    if claim["derivation"] == "ki_schlussfolgerung" and actor != "mensch":
        raise StatusRuleViolation("Eine KI-Schlussfolgerung wird nur durch menschliche Bestätigung „dokumentiert“")
    if claim["derivation"] == "aus_mehreren_abschnitten_gefolgert" and actor != "mensch":
        raise StatusRuleViolation("Gefolgerte Aussagen brauchen eine menschliche Bestätigung")
    ok = conn.execute(
        "SELECT COUNT(*) FROM evidence e JOIN source_section s ON s.id=e.section_id JOIN source q ON q.id=s.source_id "
        "WHERE e.claim_id=? AND e.relation='stützt' AND e.verified_quote=1 AND q.source_type='offizielle_doku'",
        (claim["id"],)).fetchone()[0]
    if not ok:
        raise StatusRuleViolation("Kein wörtlich verifizierter Beleg aus offizieller Dokumentation")
    if open_conflicts_for(conn, claim["id"]):
        raise StatusRuleViolation("Offener Befund (Widerspruch, Duplikat oder Einschränkung) – menschliche Prüfung nötig")


def supersede(conn, old_id: str, new_statement: str, scope: str | None, reason: str, actor: str) -> str:
    """Neue (z. B. eingeschränkte) Fassung anlegen; die alte wird zurückgezogen, Belege werden übernommen."""
    old = conn.execute("SELECT * FROM claim WHERE id=?", (old_id,)).fetchone()
    if not old:
        raise StatusRuleViolation(f"Erkenntnis {old_id} existiert nicht")
    cid = dbm.new_id(conn, "claim")
    ts = dbm.now()
    conn.execute(
        "INSERT INTO claim(id, topic_id, goal_id, statement, keywords, app, module, module_version, scope, "
        "preconditions, io_behavior, derivation, status, status_reason, supersedes_id, session_id, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (cid, old["topic_id"], old["goal_id"], new_statement, old["keywords"], old["app"], old["module"],
         old["module_version"], scope if scope is not None else old["scope"], old["preconditions"],
         old["io_behavior"], old["derivation"], "entwurf", f"Nachfolger von {old_id}: {reason}", old_id,
         old["session_id"], ts, ts))
    conn.execute("INSERT INTO claim_fts(claim_id, statement, keywords, module, scope) VALUES(?,?,?,?,?)",
                 (cid, new_statement, old["keywords"] or "", old["module"] or "", scope or old["scope"] or ""))
    for e in conn.execute("SELECT * FROM evidence WHERE claim_id=?", (old_id,)).fetchall():
        conn.execute("INSERT INTO evidence(id, claim_id, section_id, quote, relation, verified_quote) VALUES(?,?,?,?,?,?)",
                     (dbm.new_id(conn, "evidence"), cid, e["section_id"], e["quote"], e["relation"], e["verified_quote"]))
    _history(conn, cid, "angelegt", None, "entwurf", f"Nachfolger von {old_id}", actor)
    set_status(conn, old_id, "zurückgezogen", f"Ersetzt durch {cid}: {reason}", actor)
    return cid


def finalize_session_claims(conn, session_id: str) -> dict:
    """Entwürfe einer abgeschlossenen Sitzung nach Regeln einstufen. Nichts wird ohne Regel hochgestuft."""
    summary = {"dokumentiert": [], "widersprüchlich": [], "bleibt_entwurf": []}
    for c in conn.execute("SELECT * FROM claim WHERE session_id=? AND status='entwurf'", (session_id,)).fetchall():
        if open_conflicts_for(conn, c["id"], kinds=("widerspricht",)):
            set_status(conn, c["id"], "widersprüchlich", "Offener Widerspruch zu bestehender Erkenntnis", "programm")
            summary["widersprüchlich"].append(c["id"])
            continue
        try:
            set_status(conn, c["id"], "dokumentiert",
                       "Wörtlich belegt durch offizielle Dokumentation (Programmprüfung)", "programm")
            summary["dokumentiert"].append(c["id"])
        except StatusRuleViolation as exc:
            conn.execute("UPDATE claim SET status_reason=?, updated_at=? WHERE id=?",
                         (f"Bleibt Entwurf: {exc}", dbm.now(), c["id"]))
            summary["bleibt_entwurf"].append(c["id"])
    return summary


# --- Konflikte ---------------------------------------------------------------------------------

def add_conflict(conn, claim_ids: list[str], kind: str, description: str, session_id: str | None) -> str:
    kid = dbm.new_id(conn, "conflict")
    conn.execute(
        "INSERT INTO conflict(id, claim_ids, kind, description, status, session_id, created_at) VALUES(?,?,?,?,?,?,?)",
        (kid, json.dumps(claim_ids), kind, description, "offen", session_id, dbm.now()))
    if kind == "widerspricht":
        for cid in claim_ids:
            row = conn.execute("SELECT status FROM claim WHERE id=?", (cid,)).fetchone()
            if row and row["status"] in ("dokumentiert", "theoretisch_geprüft"):
                set_status(conn, cid, "widersprüchlich", f"Widerspruch {kid}: {description}", "programm")
    return kid


def open_conflicts_for(conn, claim_id: str, kinds: tuple[str, ...] = ("widerspricht", "doppelt", "schraenkt_ein")):
    rows = conn.execute("SELECT * FROM conflict WHERE status='offen' AND claim_ids LIKE ?", (f'%"{claim_id}"%',)).fetchall()
    return [r for r in rows if r["kind"] in kinds]


def open_conflicts(conn, topic_id: str | None = None):
    rows = conn.execute("SELECT * FROM conflict WHERE status='offen' ORDER BY created_at").fetchall()
    if topic_id is None:
        return rows
    out = []
    for r in rows:
        ids = json.loads(r["claim_ids"])
        if conn.execute(f"SELECT COUNT(*) FROM claim WHERE topic_id=? AND id IN ({','.join('?' * len(ids))})",
                        (topic_id, *ids)).fetchone()[0]:
            out.append(r)
    return out


# --- Abruf -------------------------------------------------------------------------------------

def retrieve_claims(conn, text: str, limit: int = 12, statuses=CURRENT_STATUSES, goal_id: str | None = None):
    q = dbm.fts_query(text)
    found: dict[str, object] = {}
    if goal_id:
        for r in conn.execute(
                f"SELECT * FROM claim WHERE goal_id=? AND status IN ({','.join('?' * len(statuses))}) ORDER BY created_at",
                (goal_id, *statuses)).fetchall():
            found[r["id"]] = r
    if q:
        rows = conn.execute(
            f"SELECT c.* FROM claim_fts f JOIN claim c ON c.id=f.claim_id WHERE claim_fts MATCH ? "
            f"AND c.status IN ({','.join('?' * len(statuses))}) ORDER BY bm25(claim_fts) LIMIT ?",
            (q, *statuses, limit)).fetchall()
        for r in rows:
            found.setdefault(r["id"], r)
    return list(found.values())


def retrieve_sections(conn, text: str, limit: int = 8):
    q = dbm.fts_query(text)
    if not q:
        return []
    return conn.execute(
        "SELECT s.*, q.title AS source_title, q.final_url AS source_url FROM section_fts f "
        "JOIN source_section s ON s.id=f.section_id JOIN source q ON q.id=s.source_id "
        "WHERE section_fts MATCH ? AND q.id = (SELECT id FROM source WHERE final_url=q.final_url ORDER BY fetched_at DESC LIMIT 1) "
        "ORDER BY bm25(section_fts) LIMIT ?", (q, limit)).fetchall()


def evidence_for(conn, claim_id: str):
    return conn.execute(
        "SELECT e.*, s.heading_path, q.final_url, q.title, q.fetched_at FROM evidence e "
        "JOIN source_section s ON s.id=e.section_id JOIN source q ON q.id=s.source_id WHERE e.claim_id=?",
        (claim_id,)).fetchall()
