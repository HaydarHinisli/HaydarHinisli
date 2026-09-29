"""Kommandozeile: `lernloop <befehl>` bzw. `python -m lernloop <befehl>`."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    from . import _toml as tomllib
from pathlib import Path

from . import catalog, exporter, knowledge, report
from . import db as dbm
from .config import CONFIG_FILENAME, ConfigError, load_config
from .fetcher import Fetcher, FetchFailed, FetchRefused
from .lock import LockHeld, SessionLock
from .model import ClaudeCodeClient, ModelError, make_client
from .session import TERMINAL, LearningSession, PauseSession, discard_session, unfinished_sessions

PKG = Path(__file__).parent
EXAMPLE_CONFIG = PKG.parent / "config" / "limits.example.toml"


def _open(cfg, read_only=False):
    if not cfg.db_path.exists():
        sys.exit("Noch nicht eingerichtet – zuerst `lernloop init` ausführen.")
    conn = dbm.connect(cfg.db_path, read_only=read_only)
    if not read_only:
        dbm.migrate(conn)
    return conn


def _fetcher_factory(cfg):
    def make(conn, sid, on_fetch):
        return Fetcher(cfg.section("fetch"), conn, sid, on_fetch=on_fetch)
    return make


def seed_topics(conn, path: Path = PKG / "topics.toml") -> int:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    added = 0
    with dbm.Tx(conn):
        dbm.migrate(conn)
        for t in data.get("topic", []):
            if conn.execute("SELECT 1 FROM topic WHERE id=?", (t["id"],)).fetchone():
                conn.execute("UPDATE topic SET preferred_hosts=? WHERE id=?",
                             (json.dumps(t.get("preferred_hosts", [])), t["id"]))
                continue
            conn.execute("INSERT INTO topic(id, title, description, prerequisites, preferred_hosts) VALUES(?,?,?,?,?)",
                         (t["id"], t["title"], t.get("description"), json.dumps(t.get("prerequisites", [])),
                          json.dumps(t.get("preferred_hosts", []))))
            for i, g in enumerate(t.get("goals", []), 1):
                conn.execute("INSERT INTO goal(id, topic_id, ord, text, updated_at) VALUES(?,?,?,?,?)",
                             (f"{t['id']}-Z{i}", t["id"], i, g, dbm.now()))
            added += 1
    return added


# --- Befehle -----------------------------------------------------------------------------------

def cmd_init(args, cfg):
    cfg_file = cfg.base_dir / CONFIG_FILENAME
    if not cfg_file.exists():
        shutil.copyfile(EXAMPLE_CONFIG, cfg_file)
        print(f"Konfiguration angelegt: {cfg_file}")
        cfg = load_config(cfg_file)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    conn = dbm.connect(cfg.db_path)
    dbm.init_schema(conn)
    n = seed_topics(conn)
    print(f"Wissensspeicher: {cfg.db_path}")
    print(f"Themen neu angelegt: {n}")
    if not cfg.section("fetch")["terms_reviewed"]:
        print("\nVor dem ersten Abruf: robots.txt und Nutzungsbedingungen von Make prüfen und dann in "
              f"{cfg_file.name} `terms_reviewed = true` setzen (Entscheidung E5).")


def cmd_doctor(args, cfg):
    ok = True
    import platform
    import sqlite3
    print(f"Python: {platform.python_version()}  SQLite: {sqlite3.sqlite_version}")
    try:
        sqlite3.connect(":memory:").execute(
            "CREATE VIRTUAL TABLE t USING fts5(a, tokenize='unicode61 remove_diacritics 2')")
        print("Volltextsuche (FTS5): OK")
    except sqlite3.OperationalError as exc:
        ok = False
        print(f"Volltextsuche (FTS5) fehlt: {exc} – bitte Python von python.org installieren")
    print(f"Konfiguration: {cfg.base_dir / CONFIG_FILENAME}"
          f"{'' if (cfg.base_dir / CONFIG_FILENAME).exists() else ' (fehlt – Standardwerte)'}")
    print(f"Datenverzeichnis: {cfg.data_dir}")
    m = cfg.section("model")
    print(f"Backend: {m['backend']}")
    if m["backend"] == "claude_code":
        client = ClaudeCodeClient(m)
        path = client.available()
        print(f"Claude Code: {path or 'NICHT GEFUNDEN'}")
        ok &= bool(path)
        import os
        if os.environ.get("ANTHROPIC_API_KEY"):
            print("Hinweis: ANTHROPIC_API_KEY ist gesetzt – der Lernloop entfernt ihn für Claude-Code-Aufrufe, "
                  "damit über das Abo und nicht nach Verbrauch abgerechnet wird.")
        if path and args.test_call:
            schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
            for use_schema in (client.use_json_schema, False) if client.use_json_schema else (False,):
                client.use_json_schema = use_schema
                label = "mit --json-schema" if use_schema else "ohne --json-schema"
                try:
                    res = client.complete("Antworte nur mit JSON.", 'Gib {"ok": true} zurück.', schema, "doctor")
                    print(f"Testaufruf {label}: OK – Modell laut Claude Code: {res.model}, Antwort: {res.data}")
                    if not use_schema and m.get("claude_code_json_schema", True):
                        print("  → In lernloop.toml `claude_code_json_schema = false` setzen.")
                    break
                except ModelError as exc:
                    print(f"Testaufruf {label} fehlgeschlagen: {exc}")
            else:
                ok = False
    f = cfg.section("fetch")
    print(f"Abruf freigegeben (terms_reviewed): {f['terms_reviewed']}")
    print(f"Freigegebene Hosts: {', '.join(f['allowed_hosts'])}")
    s = cfg.section("session")
    print(f"Limits je Sitzung: {s['max_duration_minutes']} Min., {s['max_model_calls']} Modellaufrufe, "
          f"{s['max_page_fetches']} Abrufe; Tageslimit {cfg.section('subscription_limits')['max_calls_per_day']} Aufrufe")
    if cfg.db_path.exists():
        conn = dbm.connect(cfg.db_path, read_only=True)
        print(f"Seitenkatalog: {catalog.count(conn)} Seiten; Erkenntnisse: "
              f"{conn.execute('SELECT COUNT(*) FROM claim').fetchone()[0]}")
        for r in unfinished_sessions(conn):
            print(f"Unfertige Sitzung: {r['id']} ({r['state']}, {r['paused_reason'] or 'unterbrochen'})")
    return 0 if ok else 1


def cmd_plan(args, cfg):
    conn = _open(cfg, read_only=True)
    for t in conn.execute("SELECT * FROM topic ORDER BY id"):
        print(f"{t['id']}: {t['title']}")
        for g in conn.execute("SELECT * FROM goal WHERE topic_id=? ORDER BY ord", (t["id"],)):
            print(f"  [{g['status']:>11}] {g['id']}: {g['text']}")
            if g["status_reason"] and g["status"] != "offen":
                print(f"               {g['status_reason'][:200]}")


def cmd_catalog(args, cfg):
    conn = _open(cfg)
    if args.action == "search":
        for r in catalog.search(conn, args.terms, limit=20):
            print(f"{r['url']}  {r['title'] or ''}")
        return
    with SessionLock(cfg.lock_path, f"catalog {args.action}"):
        fetcher = Fetcher(cfg.section("fetch"), conn)
        if args.action == "refresh":
            with dbm.Tx(conn):
                n = catalog.refresh_from_sitemaps(conn, fetcher)
            print(f"{n} neue Seiten; Katalog gesamt: {catalog.count(conn)}")
        elif args.action == "add":
            with dbm.Tx(conn):
                for url in args.terms:
                    fetcher.policy.check(url)
                    catalog.add_page(conn, url, None, "manuell")
            print(f"Katalog gesamt: {catalog.count(conn)}")


def cmd_learn(args, cfg):
    conn = _open(cfg)
    client = make_client(cfg)
    try:
        with SessionLock(cfg.lock_path, "learn") as lock:
            if lock.stale_previous:
                print(f"Hinweis: verwaiste Sperre eines abgebrochenen Laufs übernommen ({lock.stale_previous}).")
            if args.discard:
                discard_session(conn, args.discard, "abgebrochen_durch_nutzer")
                print(f"Sitzung {args.discard} verworfen; Entwürfe bleiben Entwürfe.")
                return 0
            unfinished = unfinished_sessions(conn)
            sess = LearningSession(cfg, conn, client, _fetcher_factory(cfg))
            if args.resume is not None:
                sid = args.resume or (unfinished[-1]["id"] if unfinished else None)
                if not sid:
                    print("Keine unterbrochene Sitzung vorhanden.")
                    return 1
            else:
                if unfinished:
                    u = unfinished[-1]
                    print(f"Es gibt eine unfertige Sitzung {u['id']} ({u['state']}, "
                          f"{u['paused_reason'] or 'ohne Pausengrund – vermutlich Absturz'}).")
                    print(f"Fortsetzen: lernloop learn --resume {u['id']}   Verwerfen: lernloop learn --discard {u['id']}")
                    return 1
                if not args.topic:
                    print("Bitte --topic angeben (siehe lernloop plan).")
                    return 1
                sid = sess.create(args.topic, args.goal)
            row = conn.execute("SELECT paused_reason, state FROM session WHERE id=?", (sid,)).fetchone()
            if args.resume is not None and row and not row["paused_reason"]:
                conn.execute("UPDATE session SET paused_reason='absturz_erkannt' WHERE id=?", (sid,))
                print(f"Sitzung {sid} wurde ohne Pause beendet (Absturz) – setze am letzten Checkpoint fort.")
            sess.load(sid)
            print(f"Sitzung {sid} ({'fortgesetzt' if args.resume is not None else 'neu'})")
            state = sess.run()
    except LockHeld as exc:
        print(exc)
        return 1
    except (ValueError, FetchRefused) as exc:
        print(f"Fehler: {exc}")
        return 1
    rep = report.session_report(conn, sid)
    print()
    print(report.render_text(rep))
    out = cfg.safe_path("reports", f"{sid}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report.render_html(rep), encoding="utf-8")
    print(f"\nBericht: {out}")
    return 0 if state == TERMINAL else 2


def cmd_ask(args, cfg):
    from .ask import answer
    conn = _open(cfg)
    client = make_client(cfg)
    try:
        with SessionLock(cfg.lock_path, "ask"):
            res = answer(cfg, conn, client, _fetcher_factory(cfg), args.question, args.variante)
    except (LockHeld, PauseSession, ModelError) as exc:
        print(exc)
        return 1
    print(res["antwort"])
    print()
    if res["offen"]:
        print("⚠ Als offen gekennzeichnet – die Belege reichen nicht für eine sichere Antwort.")
    for c in res["genutzte_erkenntnisse"]:
        print(f"  {c['id']} [{c['status']}] {c['aussage']}")
    for s in res["genutzte_abschnitte"]:
        print(f"  {s['id']} {s['url']} – {s['pfad']}")
    if res["unbelegte_teile"]:
        print("Unbelegt: " + "; ".join(res["unbelegte_teile"]))
    if res["ungültige_belege"]:
        print("Verworfene Belegangaben (nicht im übergebenen Material): " + ", ".join(res["ungültige_belege"]))
    return 0


def cmd_review(args, cfg):
    conn = _open(cfg)
    if args.action == "dedupe":
        # Offene „doppelt“-Befunde auflösen, wenn die ältere Aussage bereits gültig belegt ist.
        done = kept = 0
        with SessionLock(cfg.lock_path, "review dedupe"), dbm.Tx(conn):
            for k in conn.execute("SELECT * FROM conflict WHERE status='offen' AND kind='doppelt'").fetchall():
                new_id, old_id = json.loads(k["claim_ids"])[:2]
                gone = conn.execute("SELECT status FROM claim WHERE id=?", (new_id,)).fetchone()
                if gone and gone["status"] == "zurückgezogen":
                    # Die neue Aussage wurde schon wegen eines anderen Duplikat-Befunds zurückgezogen.
                    conn.execute("UPDATE conflict SET status='geklärt', resolution=?, resolved_at=? WHERE id=?",
                                 (f"Automatisch: {new_id} bereits zurückgezogen", dbm.now(), k["id"]))
                    print(f"  {k['id']}: erledigt ({new_id} war bereits zurückgezogen)")
                    done += 1
                    continue
                if knowledge.drop_duplicate(conn, new_id, old_id, k["description"], k["session_id"], record=False):
                    conn.execute("UPDATE conflict SET status='geklärt', resolution=?, resolved_at=? WHERE id=?",
                                 (f"Automatisch: {new_id} zurückgezogen", dbm.now(), k["id"]))
                    print(f"  {k['id']}: {new_id} zurückgezogen (Duplikat von {old_id})")
                    done += 1
                else:
                    kept += 1
            # Entwürfe, die nur wegen eines inzwischen geklärten Befunds Entwurf blieben, erneut einstufen.
            promoted = 0
            for c in conn.execute("SELECT id FROM claim WHERE status='entwurf' "
                                  "AND status_reason LIKE 'Bleibt Entwurf: Offener Befund%'").fetchall():
                try:
                    knowledge.set_status(conn, c["id"], "dokumentiert",
                                         "Befund geklärt; wörtlich belegt (Programmprüfung)", "programm")
                    promoted += 1
                except knowledge.StatusRuleViolation:
                    pass
        print(f"{done} Duplikate zurückgezogen, {kept} Befunde bleiben zur Prüfung, {promoted} Entwürfe jetzt dokumentiert.")
        return 0
    if args.action == "list":
        print("Entwürfe:")
        for c in conn.execute("SELECT * FROM claim WHERE status='entwurf' ORDER BY id"):
            print(f"  {c['id']}: {c['statement']}\n      {c['status_reason']}")
        print("Offene Befunde:")
        for k in knowledge.open_conflicts(conn):
            print(f"  {k['id']} [{k['kind']}] {', '.join(json.loads(k['claim_ids']))}: {k['description']}")
        print("Unbewertete Übungsversuche:")
        for a in conn.execute("SELECT a.*, t.prompt, t.expected FROM attempt a JOIN task t ON t.id=a.task_id "
                              "WHERE a.grade_status='offen'"):
            print(f"  {a['id']} zu {a['task_id']}: {a['prompt']}\n      Antwort: {a['answer']}\n"
                  f"      Musterlösung: {a['expected']}")
        return 0
    with SessionLock(cfg.lock_path, f"review {args.action}"):
        with dbm.Tx(conn):
            if args.action == "confirm":
                knowledge.set_status(conn, args.id, "dokumentiert", args.reason, "mensch")
            elif args.action == "retract":
                knowledge.set_status(conn, args.id, "zurückgezogen", args.reason, "mensch")
            elif args.action == "unresolved":
                knowledge.set_status(conn, args.id, "ungeklärt", args.reason, "mensch")
            elif args.action == "narrow":
                if not args.statement:
                    sys.exit("--statement fehlt")
                new = knowledge.supersede(conn, args.id, args.statement, args.scope, args.reason, "mensch")
                if args.confirm:
                    knowledge.set_status(conn, new, "dokumentiert", f"Präzisierte Fassung geprüft: {args.reason}",
                                         "mensch")
                    print(f"Neue Fassung: {new} (dokumentiert)")
                else:
                    print(f"Neue Fassung: {new} (Entwurf; mit `review confirm {new}` bestätigen)")
            elif args.action == "resolve":
                promoted = knowledge.resolve_conflict(conn, args.id, args.reason)
                if promoted:
                    print(f"  wieder dokumentiert: {', '.join(promoted)}")
            if args.close_findings and args.action in ("confirm", "retract", "unresolved", "narrow"):
                closed, promoted = knowledge.close_findings_for(conn, args.id, args.reason)
                print(f"  Befunde geschlossen: {', '.join(closed) or 'keine'}"
                      + (f"; wieder dokumentiert: {', '.join(promoted)}" if promoted else ""))
            elif args.action == "grade":
                if args.passed is None:
                    sys.exit("--bestanden oder --nicht-bestanden angeben")
                conn.execute("UPDATE attempt SET grade_status='bewertet', passed=?, grader='mensch', grade_note=?, "
                             "error_class=? WHERE id=?", (int(args.passed), args.reason, args.error_class, args.id))
                if args.passed:
                    a = conn.execute("SELECT cited_claims FROM attempt WHERE id=?", (args.id,)).fetchone()
                    for cid in json.loads(a["cited_claims"]):
                        try:
                            knowledge.set_status(conn, cid, "theoretisch_geprüft",
                                                 f"Übung {args.id} bestanden (menschlich bewertet)", "programm")
                            print(f"  {cid} → theoretisch_geprüft")
                        except knowledge.StatusRuleViolation as exc:
                            print(f"  {cid} bleibt: {exc}")
    print("Gespeichert.")
    return 0


def cmd_task(args, cfg):
    conn = _open(cfg)
    items = json.loads(Path(args.file).read_text(encoding="utf-8"))
    with SessionLock(cfg.lock_path, "task add"), dbm.Tx(conn):
        for it in items:
            if it.get("expected_source") not in ("mensch", "experiment"):
                sys.exit(f"Aufgabe ohne fachlich bestätigte Musterlösung abgelehnt: {it.get('prompt', '')[:80]}")
            tid = dbm.new_id(conn, "task")
            conn.execute(
                "INSERT INTO task(id, pool, topic_id, task_type, prompt, expected, rubric, expected_source, "
                "approved_by, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (tid, "übung", it["topic_id"], it.get("task_type", "vorhersage"), it["prompt"],
                 json.dumps(it["expected"], ensure_ascii=False), json.dumps(it.get("rubric"), ensure_ascii=False),
                 it["expected_source"], it["approved_by"], dbm.now()))
            print(f"{tid} angelegt")
    return 0


def cmd_report(args, cfg):
    conn = _open(cfg, read_only=True)
    if args.what == "coverage":
        print(report.coverage(conn))
        return 0
    sid = args.id
    if args.what == "last" or not sid:
        row = conn.execute("SELECT id FROM session ORDER BY started_at DESC LIMIT 1").fetchone()
        if not row:
            print("Noch keine Sitzung.")
            return 1
        sid = row["id"]
    print(report.render_text(report.session_report(conn, sid)))
    return 0


def cmd_claim(args, cfg):
    conn = _open(cfg, read_only=True)
    c = conn.execute("SELECT * FROM claim WHERE id=?", (args.id,)).fetchone()
    if not c:
        sys.exit("Nicht gefunden")
    for k in c.keys():
        if c[k] is not None:
            print(f"{k}: {c[k]}")
    for e in knowledge.evidence_for(conn, args.id):
        print(f"Beleg {e['id']} ({'wörtlich gefunden' if e['verified_quote'] else 'NICHT gefunden'}): "
              f"„{e['quote']}“\n   {e['final_url']} – {e['heading_path']} (abgerufen {e['fetched_at']})")
    for h in conn.execute("SELECT * FROM claim_history WHERE claim_id=? ORDER BY id", (args.id,)):
        print(f"  {h['changed_at']} {h['change']}: {h['old_status']} → {h['new_status']} ({h['actor']}) {h['reason']}")


def cmd_mcp(args, cfg):
    from .mcp import serve
    serve(cfg)
    return 0


WORKSPACE_CLAUDE_MD = """# Make-Arbeitsordner

Hier arbeitet {name} mit Make.com: Szenarien planen, bauen, Fehler finden, Fragen klären.

## Wissen
- Bei JEDER Frage oder Aufgabe zu Make zuerst das Werkzeug `make_wissen_suchen` (Server
  „make-wissen“) nutzen – mit englischen Make-Begriffen (Modulnamen, Funktionen), ggf. mehrmals.
- Antworten auf die gefundenen Erkenntnisse stützen und deren IDs nennen (z. B. ERK-000201).
  Mit `make_erkenntnis` lassen sich Zitat und Quelle zeigen.
- Status ernst nehmen: „dokumentiert“ = wörtlich in der offiziellen Doku; offener Befund oder
  „widersprüchlich“ = nur mit Vorbehalt. Nichts davon ist praktisch in Make getestet.
- Ist etwas nicht im Speicher, das offen sagen und eigenes Wissen als ungeprüft kennzeichnen.
- Bei wichtigen oder unsicheren Punkten einen Mini-Test vorschlagen: kleines Testszenario mit
  Beispieldaten, „Run once“, worauf im Ergebnis zu achten ist. Keine echten Kundendaten.

## Dateien in diesem Ordner
- `blueprints/`: exportierte Szenarien (Make: Szenario → … → Export Blueprint). Bei Fragen zu
  einem Szenario die passende Datei lesen und konkret darauf eingehen.
- `notizen/`: eigene Notizen, Kundenanforderungen, Testergebnisse.

## Sprache und Stil
- Deutsch, einfach erklärt. Schritt für Schritt, wenn es ums Bauen in Make geht.
- Den Lernloop-Ordner (`~/HaydarHinisli/make-lernloop`) hier nicht verändern.
"""


def cmd_workspace(args, cfg):
    target = Path(args.path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    for sub in ("blueprints", "notizen"):
        (target / sub).mkdir(exist_ok=True)
    md = target / "CLAUDE.md"
    if md.exists():
        print(f"{md} existiert schon – nicht überschrieben.")
    else:
        md.write_text(WORKSPACE_CLAUDE_MD.format(name=args.name), encoding="utf-8")
        print(f"Angelegt: {md}")
    print(f"Arbeitsordner: {target}\nStarten mit:  cd {target} && claude")
    return 0


def cmd_mcp_install(args, cfg):
    import subprocess
    script = PKG.parent / "mcp_server.py"
    if not cfg.db_path.exists():
        print("Noch kein Wissensspeicher – zuerst `lernloop init` und mindestens eine Lernsitzung.")
        return 1
    claude = shutil.which(cfg.section("model").get("claude_code_command", "claude"))
    if not claude:
        print("Claude Code nicht gefunden.")
        return 1
    cmd = [claude, "mcp", "add", "--scope", args.scope, "make-wissen", "--", sys.executable, str(script)]
    print("Führe aus: " + " ".join(cmd))
    rc = subprocess.run(cmd).returncode
    if rc == 0:
        print("\nFertig. Neues Claude-Code-Fenster öffnen (`claude`) und mit `/mcp` prüfen, ob 'make-wissen' "
              "verbunden ist. Danach einfach Make-Fragen stellen.")
    return rc


def cmd_export(args, cfg):
    conn = _open(cfg, read_only=True)
    print(f"Export: {exporter.export_jsonl(conn, cfg)}")


def cmd_backup(args, cfg):
    conn = _open(cfg, read_only=True)
    print(f"Sicherung: {exporter.backup(conn, cfg)}")


def cmd_restore(args, cfg):
    with SessionLock(cfg.lock_path, "restore"):
        print(f"Wiederhergestellt nach {exporter.restore(cfg, Path(args.path))}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lernloop", description="Lernsystem für Make.com mit belegbarem Wissen")
    p.add_argument("--config", type=Path, help=f"Pfad zur Konfiguration (Standard: ./{CONFIG_FILENAME})")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Konfiguration, Wissensspeicher und Themenkatalog anlegen")
    d = sub.add_parser("doctor", help="Einrichtung prüfen")
    d.add_argument("--test-call", action="store_true", help="einen kleinen Testaufruf an Claude senden")
    sub.add_parser("plan", help="Themen und Lernziele anzeigen")

    c = sub.add_parser("catalog", help="Seitenkatalog der Doku")
    c.add_argument("action", choices=["refresh", "search", "add"])
    c.add_argument("terms", nargs="*")

    l = sub.add_parser("learn", help="Lernsitzung starten oder fortsetzen")
    l.add_argument("--topic")
    l.add_argument("--goal")
    l.add_argument("--resume", nargs="?", const="", help="unterbrochene Sitzung fortsetzen (ID optional)")
    l.add_argument("--discard", metavar="SITZUNG", help="unfertige Sitzung verwerfen")

    a = sub.add_parser("ask", help="Frage beantworten (mit Belegen)")
    a.add_argument("question")
    a.add_argument("--variante", choices=["A", "B"], default="B",
                   help="A = nur Dokumentationssuche, B = zusätzlich Lernspeicher")

    r = sub.add_parser("review", help="Entwürfe, Befunde und Übungen prüfen (Mensch)")
    r.add_argument("action", choices=["list", "dedupe", "confirm", "retract", "unresolved", "narrow", "resolve",
                                      "grade"])
    r.add_argument("id", nargs="?")
    r.add_argument("--reason", default="")
    r.add_argument("--statement")
    r.add_argument("--scope")
    r.add_argument("--bestaetigen", dest="confirm", action="store_true",
                   help="bei narrow: neue Fassung gleich als geprüft bestätigen")
    r.add_argument("--befunde-schliessen", dest="close_findings", action="store_true",
                   help="alle offenen Befunde zu dieser Erkenntnis mit derselben Begründung schließen")
    g = r.add_mutually_exclusive_group()
    g.add_argument("--bestanden", dest="passed", action="store_true", default=None)
    g.add_argument("--nicht-bestanden", dest="passed", action="store_false")
    r.add_argument("--error-class", choices=["quellenproblem", "abrufproblem", "anwendungsfehler",
                                             "beweislage_unzureichend"])

    t = sub.add_parser("task", help="Übungsaufgaben mit bestätigter Musterlösung importieren")
    t.add_argument("action", choices=["add"])
    t.add_argument("file")

    rp = sub.add_parser("report", help="Berichte")
    rp.add_argument("what", choices=["session", "last", "coverage"])
    rp.add_argument("id", nargs="?")

    cl = sub.add_parser("claim", help="Erkenntnis mit Belegen und Verlauf anzeigen")
    cl.add_argument("id")

    sub.add_parser("mcp", help="MCP-Server für Claude Code/Desktop starten (wird von Claude aufgerufen)")
    mi = sub.add_parser("mcp-install", help="Wissensspeicher als 'make-wissen' in Claude Code eintragen")
    mi.add_argument("--scope", choices=["user", "local", "project"], default="user",
                    help="user = in allen Claude-Code-Fenstern verfügbar (Standard)")
    ws = sub.add_parser("arbeitsordner", help="Ordner für die tägliche Make-Arbeit mit Claude anlegen")
    ws.add_argument("--path", default="~/make-arbeit")
    ws.add_argument("--name", default="der Nutzer")
    sub.add_parser("export", help="Wissensbestand als JSON Lines exportieren")
    sub.add_parser("backup", help="Sicherung der Datenbank anlegen")
    rs = sub.add_parser("restore", help="Sicherung wiederherstellen")
    rs.add_argument("path")
    return p


COMMANDS = {"init": cmd_init, "doctor": cmd_doctor, "plan": cmd_plan, "catalog": cmd_catalog, "learn": cmd_learn,
            "ask": cmd_ask, "review": cmd_review, "task": cmd_task, "report": cmd_report, "claim": cmd_claim,
            "export": cmd_export, "backup": cmd_backup, "restore": cmd_restore, "mcp": cmd_mcp,
            "mcp-install": cmd_mcp_install, "arbeitsordner": cmd_workspace}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Konfigurationsfehler: {exc}")
        return 1
    if args.cmd == "review" and args.action not in ("list", "dedupe"):
        if not args.id:
            print("ID fehlt")
            return 1
        if args.action != "grade" and not args.reason.strip():
            print("--reason ist Pflicht (Begründung wird protokolliert)")
            return 1
    try:
        return COMMANDS[args.cmd](args, cfg) or 0
    except LockHeld as exc:
        print(exc)
        return 1
    except (knowledge.StatusRuleViolation, FetchRefused, FetchFailed, ModelError) as exc:
        print(f"Abgelehnt: {exc}")
        return 1
