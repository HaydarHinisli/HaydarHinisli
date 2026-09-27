"""Sitzungs- und Abdeckungsberichte – ausschließlich aus gespeicherten Daten."""

from __future__ import annotations

import html
import json

from . import knowledge


def session_report(conn, sid: str) -> dict:
    s = conn.execute("SELECT * FROM session WHERE id=?", (sid,)).fetchone()
    if not s:
        raise ValueError(f"Sitzung {sid} nicht gefunden")
    ctx = json.loads(s["context"])
    goal = conn.execute("SELECT * FROM goal WHERE id=?", (s["goal_id"],)).fetchone()
    topic = conn.execute("SELECT * FROM topic WHERE id=?", (s["topic_id"],)).fetchone()
    sources = conn.execute("SELECT id, title, final_url, fetched_at FROM source WHERE session_id=? ORDER BY fetched_at",
                           (sid,)).fetchall()
    claims = conn.execute("SELECT * FROM claim WHERE session_id=? ORDER BY id", (sid,)).fetchall()
    calls = conn.execute(
        "SELECT COUNT(*) n, SUM(COALESCE(input_tokens,0)) inp, SUM(COALESCE(output_tokens,0)) outp, "
        "SUM(COALESCE(cache_read_tokens,0)) cached, SUM(COALESCE(duration_ms,0)) ms, SUM(1-ok) failed, "
        "SUM(COALESCE(cost_usd_equiv,0)) cost FROM model_call WHERE session_id=?", (sid,)).fetchone()
    fetches = conn.execute("SELECT COUNT(*) FROM fetch_log WHERE session_id=?", (sid,)).fetchone()[0]
    attempts = conn.execute("SELECT * FROM attempt WHERE session_id=?", (sid,)).fetchall()
    conflicts = conn.execute("SELECT * FROM conflict WHERE session_id=?", (sid,)).fetchall()
    return {
        "sitzung": sid, "zustand": s["state"], "pausiert": s["paused_reason"],
        "thema": topic["title"], "lernziel": goal["text"], "lernziel_status": goal["status"],
        "abschlussgrund": s["end_reason"], "detail": s["end_detail"],
        "start": s["started_at"], "ende": s["ended_at"], "aktive_minuten": round(s["active_seconds"] / 60, 1),
        "runden": [{"nr": r["nr"], "frage": r.get("question"), "suchbegriffe": r.get("terms"),
                    "beurteilung": r.get("assessment")} for r in ctx.get("rounds", [])],
        "fehlerklassen": ctx.get("error_classes", []),
        "quellen": [dict(r) for r in sources],
        "erkenntnisse": [{"id": c["id"], "status": c["status"], "aussage": c["statement"],
                          "grund": c["status_reason"],
                          "belege": [{"url": e["final_url"], "abschnitt": e["heading_path"], "zitat": e["quote"],
                                      "wörtlich_gefunden": bool(e["verified_quote"])}
                                     for e in knowledge.evidence_for(conn, c["id"])]} for c in claims],
        "widersprüche_und_befunde": [{"id": k["id"], "art": k["kind"], "erkenntnisse": json.loads(k["claim_ids"]),
                                      "beschreibung": k["description"], "status": k["status"]} for k in conflicts],
        "übungen": [{"aufgabe": a["task_id"], "bewertung": a["grade_status"], "bestanden": a["passed"]}
                    for a in attempts] or ctx.get("practice_note"),
        "verbrauch": {"modellaufrufe": calls["n"], "davon_fehlgeschlagen": calls["failed"] or 0,
                      "eingabe_tokens": calls["inp"] or 0, "ausgabe_tokens": calls["outp"] or 0,
                      "cache_tokens": calls["cached"] or 0, "modellzeit_s": round((calls["ms"] or 0) / 1000),
                      "kostenäquivalent_usd_laut_claude_code": round(calls["cost"] or 0, 4),
                      "seitenabrufe": fetches},
    }


def render_text(rep: dict) -> str:
    L = []
    L.append(f"Sitzung {rep['sitzung']} – {rep['thema']}")
    L.append(f"Lernziel: {rep['lernziel']}  → Status: {rep['lernziel_status']}")
    if rep["pausiert"]:
        L.append(f"PAUSIERT: {rep['pausiert']}")
    L.append(f"Abschlussgrund: {rep['abschlussgrund'] or '-'}  ({rep['detail'] or ''})")
    L.append(f"Dauer (aktiv): {rep['aktive_minuten']} Min.")
    for r in rep["runden"]:
        a = r["beurteilung"] or {}
        L.append(f"  Runde {r['nr']}: {r['frage']}")
        if a:
            L.append(f"    → {a.get('ergebnis')} / {a.get('fehlerklasse')}: {a.get('begruendung')}")
    L.append(f"Quellen ({len(rep['quellen'])}):")
    for q in rep["quellen"]:
        L.append(f"  {q['id']}  {q['final_url']}  (abgerufen {q['fetched_at']})")
    L.append(f"Erkenntnisse ({len(rep['erkenntnisse'])}):")
    for c in rep["erkenntnisse"]:
        L.append(f"  [{c['status']}] {c['id']}: {c['aussage']}")
        for b in c["belege"]:
            mark = "✓" if b["wörtlich_gefunden"] else "✗"
            L.append(f"      {mark} „{b['zitat'][:160]}“ – {b['url']}")
        if c["status"] == "entwurf":
            L.append(f"      Grund: {c['grund']}")
    if rep["widersprüche_und_befunde"]:
        L.append("Befunde:")
        for k in rep["widersprüche_und_befunde"]:
            L.append(f"  {k['id']} [{k['art']}, {k['status']}] {', '.join(k['erkenntnisse'])}: {k['beschreibung']}")
    L.append(f"Übungen: {rep['übungen']}")
    v = rep["verbrauch"]
    L.append(f"Verbrauch: {v['modellaufrufe']} Modellaufrufe ({v['davon_fehlgeschlagen']} fehlgeschlagen), "
             f"{v['eingabe_tokens']} Eingabe- / {v['ausgabe_tokens']} Ausgabe-Tokens, "
             f"{v['seitenabrufe']} Seitenabrufe")
    return "\n".join(L)


def render_html(rep: dict) -> str:
    body = html.escape(render_text(rep))
    return (f"<!doctype html><html lang='de'><head><meta charset='utf-8'><title>Sitzung {rep['sitzung']}</title>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 16px;"
            "background:#fff;color:#111}pre{white-space:pre-wrap}"
            "@media (prefers-color-scheme:dark){body{background:#111;color:#eee}}</style></head>"
            f"<body><h1>Lernsitzung {rep['sitzung']}</h1><pre>{body}</pre></body></html>")


def coverage(conn) -> str:
    L = []
    for t in conn.execute("SELECT * FROM topic ORDER BY id"):
        goals = conn.execute("SELECT * FROM goal WHERE topic_id=? ORDER BY ord", (t["id"],)).fetchall()
        counts: dict[str, int] = {}
        for g in goals:
            counts[g["status"]] = counts.get(g["status"], 0) + 1
        L.append(f"{t['id']}: {t['title']}")
        L.append(f"  Lernziele: {len(goals)} – " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
        for g in goals:
            n = conn.execute("SELECT status, COUNT(*) n FROM claim WHERE goal_id=? GROUP BY status", (g["id"],)).fetchall()
            detail = ", ".join(f"{r['status']} {r['n']}" for r in n) or "keine Erkenntnisse"
            L.append(f"   [{g['status']}] {g['id']} {g['text']}  ({detail})")
        k = len(knowledge.open_conflicts(conn, t["id"]))
        L.append(f"  Offene Befunde/Widersprüche: {k}")
    L.append("Hinweis: Abdeckung bezieht sich nur auf den benannten Themenkatalog – keine Gesamtaussage über Make.")
    return "\n".join(L)
