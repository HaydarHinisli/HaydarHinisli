"""MCP-Server (stdio): stellt den geprüften Make-Wissensspeicher für Claude Code / Claude Desktop bereit.

Nur lesend – der Server öffnet die Datenbank schreibgeschützt und kann nichts verändern.
Er ruft kein Modell auf; das Denken übernimmt das Chatfenster, das ihn benutzt.
Protokoll: JSON-RPC 2.0, eine Nachricht pro Zeile auf stdin/stdout. Ausgaben für Menschen gehen
nach stderr, damit stdout sauber bleibt.
"""

from __future__ import annotations

import json
import sys

from . import __version__, knowledge, report
from . import db as dbm

PROTOCOL_VERSION = "2025-06-18"

INSTRUCTIONS = """Dieser Server liefert geprüftes Wissen über Make.com aus dem lokalen Lernloop des Nutzers.

So nutzt du ihn bei jeder Frage oder Aufgabe zu Make (Szenarien bauen, Module, Mapping, Bundles, \
Iterator/Aggregator, Funktionen, Operations/Credits, Fehler):
1. Rufe zuerst make_wissen_suchen auf – mit Modulnamen und Fachbegriffen auf Englisch (so heißen sie \
in Make), bei Bedarf mehrmals mit anderen Begriffen.
2. Stütze deine Antwort auf die gefundenen Erkenntnisse und nenne ihre IDs (ERK-…), damit der Nutzer \
sie nachprüfen kann (make_erkenntnis zeigt Zitat und Quelle).
3. Status beachten: „dokumentiert“ = wörtlich in der offiziellen Doku belegt; „theoretisch_geprüft“ = \
zusätzlich in einer menschlich bewerteten Übung bestätigt; „widersprüchlich“ oder ein offener Befund = \
nur mit Vorbehalt verwenden; „ungeklärt“ = die Doku belegt es nicht. Nichts davon ist praktisch in Make \
getestet.
4. Findest du nichts, sag das offen und kennzeichne alles Weitere als eigenes, ungeprüftes Wissen. \
Erfinde keine Belege.
5. Randfälle, die die Doku nicht beschreibt (z. B. leeres Array im Iterator), empfiehl im Zweifel kurz \
in einem Testszenario auszuprobieren."""

TOOLS = [
    {
        "name": "make_wissen_suchen",
        "description": ("Durchsucht den geprüften Make.com-Wissensspeicher (Erkenntnisse mit wörtlichem Beleg aus "
                        "der offiziellen Doku) und passende Doku-Abschnitte. Vor jeder Antwort zu Make aufrufen."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "suchbegriffe": {"type": "string",
                                 "description": "Stichworte, am besten englische Make-Begriffe, z. B. "
                                                "'array aggregator group by' oder 'slice index'"},
                "mit_doku_abschnitten": {"type": "boolean",
                                         "description": "Zusätzlich passende Originalabschnitte der Doku liefern "
                                                        "(Standard: true)"},
            },
            "required": ["suchbegriffe"],
        },
    },
    {
        "name": "make_erkenntnis",
        "description": "Zeigt eine Erkenntnis (ERK-…) vollständig: Aussage, Geltungsbereich, Status, wörtliche "
                       "Belege mit URL und Abrufdatum, Verlauf.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "z. B. ERK-000201"}},
            "required": ["id"],
        },
    },
    {
        "name": "make_themenstand",
        "description": "Übersicht, welche Lernziele im Themenkatalog beantwortet, teilweise oder offen sind, "
                       "und welche Fragen die Doku bisher nicht belegt. Nützlich, um Wissenslücken zu kennen.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class Server:
    def __init__(self, cfg):
        self.cfg = cfg

    def _conn(self):
        if not self.cfg.db_path.exists():
            raise RuntimeError("Wissensspeicher nicht gefunden – im Lernloop zuerst `lernloop init` ausführen.")
        return dbm.connect(self.cfg.db_path, read_only=True)

    # --- Werkzeuge ---------------------------------------------------------------------
    def suchen(self, args: dict) -> str:
        q = (args.get("suchbegriffe") or "").strip()
        if not q:
            return "Bitte Suchbegriffe angeben."
        conn = self._conn()
        claims = knowledge.retrieve_claims(conn, q, limit=15)
        out = [f"Suche: {q}", ""]
        if claims:
            out.append(f"Erkenntnisse ({len(claims)}):")
            for c in claims:
                ev = knowledge.evidence_for(conn, c["id"])
                url = next((e["final_url"] for e in ev if e["verified_quote"]), ev[0]["final_url"] if ev else "-")
                out.append(f"- {c['id']} [{c['status']}] {c['statement']}")
                if c.get("scope"):
                    out.append(f"    Geltungsbereich: {c['scope']}")
                if c.get("offener_befund"):
                    out.append(f"    ACHTUNG offener Befund: {c['offener_befund']}")
                out.append(f"    Quelle: {url}")
        else:
            out.append("Keine geprüften Erkenntnisse zu diesen Begriffen.")
        if args.get("mit_doku_abschnitten", True):
            secs = knowledge.retrieve_sections(conn, q, limit=4)
            if secs:
                out.append("")
                out.append("Passende Doku-Abschnitte (Originaltext, noch nicht als Erkenntnis geprüft):")
                for s in secs:
                    text = s["text"] if len(s["text"]) <= 1200 else s["text"][:1200] + " …"
                    out.append(f"- {s['id']} {s['source_url']} – {s['heading_path']}\n{text}")
        out.append("")
        out.append("Hinweis: Wissen aus der offiziellen Doku, nicht praktisch in Make getestet.")
        return "\n".join(out)

    def erkenntnis(self, args: dict) -> str:
        cid = (args.get("id") or "").strip().upper()
        conn = self._conn()
        c = conn.execute("SELECT * FROM claim WHERE id=?", (cid,)).fetchone()
        if not c:
            return f"{cid} nicht gefunden."
        lines = [f"{c['id']} [{c['status']}]", c["statement"], f"Geltungsbereich: {c['scope'] or '-'}",
                 f"Voraussetzungen: {c['preconditions'] or '-'}", f"Ableitung: {c['derivation']}",
                 f"Status-Begründung: {c['status_reason']}"]
        if c["status"] == "zurückgezogen":
            newer = conn.execute("SELECT id FROM claim WHERE supersedes_id=?", (cid,)).fetchone()
            if newer:
                lines.append(f"Ersetzt durch: {newer['id']}")
        for e in knowledge.evidence_for(conn, cid):
            lines.append(f"Beleg ({'wörtlich gefunden' if e['verified_quote'] else 'NICHT gefunden'}): "
                         f"„{e['quote']}“ – {e['final_url']} ({e['heading_path']}, abgerufen {e['fetched_at']})")
        for k in knowledge.open_conflicts_for(conn, cid):
            lines.append(f"Offener Befund {k['id']} ({k['kind']}): {k['description']}")
        return "\n".join(lines)

    def themenstand(self, args: dict) -> str:
        conn = self._conn()
        text = report.coverage(conn)
        oq = conn.execute("SELECT text, status FROM open_question WHERE status IN ('offen','ungeklärt') "
                          "ORDER BY created_at DESC LIMIT 15").fetchall()
        if oq:
            text += "\n\nOffene bzw. von der Doku nicht belegte Fragen (Auswahl):\n" + "\n".join(
                f"- [{r['status']}] {r['text']}" for r in oq)
        return text

    # --- JSON-RPC ----------------------------------------------------------------------
    def handle(self, msg: dict):
        method, mid = msg.get("method"), msg.get("id")
        if method == "initialize":
            requested = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL_VERSION
            return _ok(mid, {"protocolVersion": requested, "capabilities": {"tools": {}},
                             "serverInfo": {"name": "make-wissen", "version": __version__},
                             "instructions": INSTRUCTIONS})
        if method == "ping":
            return _ok(mid, {})
        if method == "tools/list":
            return _ok(mid, {"tools": TOOLS})
        if method == "tools/call":
            params = msg.get("params") or {}
            fn = {"make_wissen_suchen": self.suchen, "make_erkenntnis": self.erkenntnis,
                  "make_themenstand": self.themenstand}.get(params.get("name"))
            if not fn:
                return _err(mid, -32602, f"Unbekanntes Werkzeug: {params.get('name')}")
            try:
                text, is_error = fn(params.get("arguments") or {}), False
            except Exception as exc:  # Fehler als Werkzeug-Ergebnis zurückgeben, Server läuft weiter
                text, is_error = f"Fehler: {exc}", True
            return _ok(mid, {"content": [{"type": "text", "text": text}], "isError": is_error})
        if mid is None:
            return None  # Benachrichtigung (z. B. notifications/initialized) – keine Antwort
        return _err(mid, -32601, f"Methode nicht unterstützt: {method}")


def _ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def serve(cfg, stdin=None, stdout=None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    server = Server(cfg)
    print(f"make-wissen MCP-Server bereit ({cfg.db_path})", file=sys.stderr)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            resp = _err(None, -32700, "Ungültiges JSON")
        else:
            resp = server.handle(msg) if isinstance(msg, dict) else _err(None, -32600, "Ungültige Anfrage")
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            stdout.flush()
