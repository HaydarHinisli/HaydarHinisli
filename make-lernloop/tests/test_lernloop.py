import json
import re
import os
import sqlite3
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from lernloop import catalog, exporter, knowledge, model
from lernloop import db as dbm
from lernloop.extract import parse_html, quote_in_text
from lernloop.fetcher import Fetcher, FetchRefused, UrlPolicy
from lernloop.lock import LockHeld, SessionLock
from lernloop.model import FakeClient, ModelError, UsageLimitReached, parse_claude_output
from lernloop.session import TERMINAL, LearningSession, discard_session

from .helpers import FIX, FakeWeb, fetcher_factory, good_responder, make_env, resolver_public


def run_session(cfg, conn, web, responder, topic="T01", goal="T01-Z2"):
    sess = LearningSession(cfg, conn, FakeClient(responder), fetcher_factory(cfg, web), log=lambda *a: None)
    sid = sess.create(topic, goal)
    sess.load(sid)
    return sid, sess.run()


class FetchPolicyTests(unittest.TestCase):
    def setUp(self):
        self.cfg, self.conn, _ = make_env()
        self.web = FakeWeb()

    def fetcher(self, resolver=resolver_public, **over):
        f = dict(self.cfg.section("fetch"), **over)
        return Fetcher(f, self.conn, transport=self.web.transport, resolver=resolver, sleep=lambda s: None)

    def test_only_https_and_allowlisted_hosts(self):
        f = self.fetcher()
        with self.assertRaises(FetchRefused):
            f.fetch("http://help.make.com/iterator")
        with self.assertRaises(FetchRefused):
            f.fetch("https://evil.example.com/iterator")
        with self.assertRaises(FetchRefused):
            f.fetch("https://user:pw@help.make.com/iterator")
        self.assertEqual(f.fetch("https://help.make.com/iterator").status, 200)

    def test_private_address_refused(self):
        f = self.fetcher(resolver=lambda h: __import__("lernloop.fetcher").fetcher.resolve_public("localhost"))
        with self.assertRaises(FetchRefused):
            f.fetch("https://help.make.com/iterator")

    def test_redirect_to_foreign_host_refused(self):
        self.web.redirects["/iterator"] = "https://169.254.169.254/latest/meta-data"
        with self.assertRaises(FetchRefused):
            self.fetcher().fetch("https://help.make.com/iterator")

    def test_terms_gate(self):
        with self.assertRaises(FetchRefused) as ctx:
            self.fetcher(terms_reviewed=False).fetch("https://help.make.com/iterator")
        self.assertIn("terms_reviewed", str(ctx.exception))
        self.assertEqual(self.web.requests, [])  # kein einziger Netzwerkzugriff

    def test_terms_gate_also_blocks_robots_and_sitemaps(self):
        f = self.fetcher(terms_reviewed=False)
        with self.assertRaises(FetchRefused):
            f.robots_sitemaps("help.make.com")
        with self.assertRaises(FetchRefused):
            catalog.refresh_from_sitemaps(self.conn, f, log=lambda *a: None)
        self.assertEqual(self.web.requests, [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM fetch_log").fetchone()[0], 0)

    def test_robots_disallow(self):
        self.web.pages["/robots.txt"] = (200, "text/plain", "User-agent: *\nDisallow: /iterator\n")
        with self.assertRaises(FetchRefused):
            self.fetcher().fetch("https://help.make.com/iterator")

    def test_preferred_hosts_come_first(self):
        with dbm.Tx(self.conn):
            catalog.add_page(self.conn, "https://developers.make.com/custom-apps/iterator", None, "t")
            catalog.add_page(self.conn, "https://help.make.com/iterator", None, "t")
        urls = [r["url"] for r in catalog.search(self.conn, ["iterator"], prefer_hosts=["help.make.com"])]
        self.assertEqual(urls[0], "https://help.make.com/iterator")
        self.assertEqual(len(urls), 2)

    def test_migration_adds_column_to_old_database(self):
        old = sqlite3.connect(":memory:")
        old.row_factory = sqlite3.Row
        old.execute("CREATE TABLE topic (id TEXT PRIMARY KEY, title TEXT)")
        old.execute("INSERT INTO topic VALUES('T01','x')")
        dbm.migrate(old)
        self.assertEqual(old.execute("SELECT preferred_hosts FROM topic").fetchone()[0], "[]")

    def test_path_prefix_policy(self):
        p = UrlPolicy([], {"www.make.com": ["/en/pricing"]})
        self.assertTrue(p.allows("https://www.make.com/en/pricing"))
        self.assertFalse(p.allows("https://www.make.com/en/login"))

    def test_catalog_from_sitemap_ignores_foreign_urls(self):
        with dbm.Tx(self.conn):
            n = catalog.refresh_from_sitemaps(self.conn, self.fetcher(), log=lambda *a: None)
        self.assertEqual(n, 3)
        urls = [r["url"] for r in catalog.search(self.conn, ["iterator"])]
        self.assertEqual(urls, ["https://help.make.com/iterator"])


class ExtractAndQuoteTests(unittest.TestCase):
    def test_scripts_and_nav_removed(self):
        page = parse_html((FIX / "iterator.html").read_text(), "https://help.make.com/iterator")
        text = "\n".join(s.text for s in page.sections)
        self.assertNotIn("alert", text)
        self.assertNotIn("Menü", text)
        self.assertEqual(page.updated_at, "2026-05-01T10:00:00Z")
        self.assertIn("Iterator > Output", [s.heading_path for s in page.sections])

    def test_quote_verification(self):
        text = "Each item of the array is output as a separate bundle.  Modules placed after run once."
        self.assertTrue(quote_in_text("each item of the array is output as a separate  bundle", text))
        self.assertTrue(quote_in_text("Each item of the array ... placed after run once", text))
        self.assertFalse(quote_in_text("Each item is sorted alphabetically.", text))
        self.assertFalse(quote_in_text("bundle", text))  # zu kurz, um etwas zu belegen


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.cfg, self.conn, _ = make_env()
        self.web = FakeWeb()

    def test_full_session(self):
        sid, state = run_session(self.cfg, self.conn, self.web, good_responder)
        self.assertEqual(state, TERMINAL)
        s = self.conn.execute("SELECT * FROM session WHERE id=?", (sid,)).fetchone()
        self.assertEqual(s["end_reason"], "ziel_erreicht")
        claims = {c["statement"]: c for c in self.conn.execute("SELECT * FROM claim")}
        self.assertEqual(claims["Der Iterator gibt jedes Array-Element als eigenes Bundle aus."]["status"], "dokumentiert")
        # erfundenes Zitat → bleibt Entwurf
        self.assertEqual(claims["Der Iterator sortiert die Elemente alphabetisch."]["status"], "entwurf")
        # KI-Schlussfolgerung → trotz korrektem Zitat nur Entwurf
        ki = claims["Nach dem Iterator laufen Folgemodule pro Bundle, daher steigt der Verbrauch."]
        self.assertEqual(ki["status"], "entwurf")
        self.assertIn("menschliche Bestätigung", ki["status_reason"])
        # nicht in Kandidatenliste vorgeschlagene URL wurde nicht abgerufen
        self.assertNotIn(("help.make.com", "93.184.216.34", "/erfunden"), self.web.requests)
        goal = self.conn.execute("SELECT status FROM goal WHERE id='T01-Z2'").fetchone()
        self.assertEqual(goal["status"], "beantwortet")
        from lernloop import report
        text = report.render_text(report.session_report(self.conn, sid))
        self.assertIn("ziel_erreicht", text)
        self.assertIn("Keine fachlich bestätigten Übungsaufgaben", text)

    def test_session_stops_at_model_call_limit(self):
        cfg, conn, _ = make_env("[session]\nmax_model_calls = 2\n")
        sid, state = run_session(cfg, conn, self.web, good_responder)
        self.assertEqual(state, TERMINAL)
        s = conn.execute("SELECT * FROM session WHERE id=?", (sid,)).fetchone()
        self.assertEqual(s["end_reason"], "limit_erreicht")
        self.assertIn("Modellaufrufe", s["end_detail"])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM model_call").fetchone()[0], 2)

    def test_session_stops_at_fetch_limit(self):
        cfg, conn, _ = make_env("[session]\nmax_page_fetches = 1\n")
        sid, state = run_session(cfg, conn, self.web, good_responder)
        s = conn.execute("SELECT * FROM session WHERE id=?", (sid,)).fetchone()
        self.assertEqual(s["end_reason"], "limit_erreicht")
        self.assertLessEqual(conn.execute("SELECT COUNT(*) FROM fetch_log").fetchone()[0], 1)

    def test_crash_then_resume(self):
        def crashing(step, prompt, schema):
            if step == "abgleich":
                raise KeyboardInterrupt  # Abbruch nach der Extraktion
            return good_responder(step, prompt, schema)

        cfg, conn = self.cfg, self.conn
        # Vorab eine bestehende Erkenntnis, damit der Abgleich-Schritt wirklich aufgerufen wird
        with dbm.Tx(conn):
            conn.execute("INSERT INTO claim(id, statement, keywords, derivation, status, status_reason, created_at, "
                         "updated_at) VALUES('ERK-900000','Iterator bundle Altbestand','iterator bundle',"
                         "'direkt_zitiert','dokumentiert','Test',?,?)", (dbm.now(), dbm.now()))
            conn.execute("INSERT INTO claim_fts(claim_id, statement, keywords, module, scope) "
                         "VALUES('ERK-900000','Iterator bundle Altbestand','iterator bundle','','')")
        sid, state = run_session(cfg, conn, self.web, crashing)
        self.assertEqual(state, "PAUSIERT")
        drafts = conn.execute("SELECT status FROM claim WHERE session_id=?", (sid,)).fetchall()
        self.assertTrue(drafts)
        self.assertTrue(all(r["status"] == "entwurf" for r in drafts))  # nichts ungeprüft hochgestuft
        fetches_before = conn.execute("SELECT COUNT(*) FROM fetch_log").fetchone()[0]

        sess = LearningSession(cfg, conn, FakeClient(good_responder), fetcher_factory(cfg, self.web),
                               log=lambda *a: None)
        sess.load(sid)
        self.assertEqual(sess.run(), TERMINAL)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM fetch_log").fetchone()[0], fetches_before)  # kein Neuabruf
        statuses = [r["status"] for r in conn.execute("SELECT status FROM claim WHERE session_id=?", (sid,))]
        self.assertIn("dokumentiert", statuses)

    def test_usage_limit_pauses(self):
        def limited(step, prompt, schema):
            raise UsageLimitReached("Claude AI usage limit reached")

        sid, state = run_session(self.cfg, self.conn, self.web, limited)
        self.assertEqual(state, "PAUSIERT")
        row = self.conn.execute("SELECT * FROM session WHERE id=?", (sid,)).fetchone()
        self.assertIn("Nutzungslimit", row["paused_reason"])

    def test_invalid_schema_retried_once_then_pauses(self):
        def bad(step, prompt, schema):
            return {"falsch": True}

        sid, state = run_session(self.cfg, self.conn, self.web, bad)
        self.assertEqual(state, "PAUSIERT")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM model_call WHERE ok=0").fetchone()[0], 2)

    def test_discard_keeps_drafts(self):
        def crashing(step, prompt, schema):
            if step == "beurteilung":
                raise ModelError("kaputt")
            return good_responder(step, prompt, schema)

        sid, state = run_session(self.cfg, self.conn, self.web, crashing)
        discard_session(self.conn, sid, "abgebrochen_durch_nutzer")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM claim WHERE status!='entwurf' AND session_id=?",
                                           (sid,)).fetchone()[0], 0)

    def test_no_session_without_terms_review(self):
        cfg, conn, _ = make_env("")
        cfg.raw["fetch"]["terms_reviewed"] = False
        client = FakeClient(good_responder)
        sess = LearningSession(cfg, conn, client, fetcher_factory(cfg, self.web), log=lambda *a: None)
        with self.assertRaises(ValueError):
            sess.create("T01")
        self.assertEqual(client.calls, [])

    def test_not_provable_without_sources_is_retrieval_problem(self):
        def responder(step, prompt, schema):
            if step == "plan":
                return {"bereits_beantwortet": False, "frage": "?", "begruendung": "-", "suchbegriffe_en": ["zzzz"]}
            if step == "beurteilung":
                return {"ergebnis": "nicht_belegbar", "begruendung": "keine Quellen", "fehlende_information": [],
                        "fehlerklasse": "abrufproblem", "naechste_suchbegriffe_en": []}
            return good_responder(step, prompt, schema)

        sid, state = run_session(self.cfg, self.conn, self.web, responder)
        s = self.conn.execute("SELECT * FROM session WHERE id=?", (sid,)).fetchone()
        self.assertEqual(s["end_reason"], "kein_fortschritt")
        self.assertEqual(self.conn.execute("SELECT status FROM goal WHERE id='T01-Z2'").fetchone()[0], "offen")

    def test_duplicate_from_later_session_is_dropped_and_page_knowledge_shown(self):
        run_session(self.cfg, self.conn, self.web, good_responder)  # ERK-000001 wird dokumentiert
        prompts_seen = []

        def responder(step, prompt, schema):
            if step == "extraktion":
                prompts_seen.append(prompt)
            if step == "abgleich":
                new = re.findall(r'erkenntnis id="(ERK-\d+)"', prompt.split("Bestehende Aussagen")[0])
                return {"befunde": [{"neu": new[0], "bestehend": "ERK-000001", "art": "doppelt",
                                     "erklaerung": "gleiche Aussage"}]}
            return good_responder(step, prompt, schema)

        sid, _ = run_session(self.cfg, self.conn, self.web, responder, goal="T01-Z3")
        self.assertIn("Der Iterator gibt jedes Array-Element als eigenes Bundle aus.", prompts_seen[0])
        dropped = self.conn.execute("SELECT status, status_reason FROM claim WHERE session_id=? ORDER BY id",
                                    (sid,)).fetchone()
        self.assertEqual(dropped["status"], "zurückgezogen")
        self.assertIn("Duplikat von ERK-000001", dropped["status_reason"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM conflict WHERE status='offen'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT status FROM claim WHERE id='ERK-000001'").fetchone()[0],
                         "dokumentiert")

    def test_review_dedupe_cleans_up_existing_duplicate_findings(self):
        from lernloop.cli import main
        run_session(self.cfg, self.conn, self.web, good_responder)
        sid, _ = run_session(self.cfg, self.conn, self.web, good_responder, goal="T01-Z3")
        new_id = self.conn.execute("SELECT id FROM claim WHERE session_id=? ORDER BY id", (sid,)).fetchone()["id"]
        with dbm.Tx(self.conn):
            self.conn.execute("UPDATE claim SET status='entwurf' WHERE id=?", (new_id,))
            knowledge.add_conflict(self.conn, [new_id, "ERK-000001"], "doppelt", "gleich", sid)
        with mock.patch("builtins.print"):
            self.assertEqual(main(["--config", str(self.cfg.base_dir / "lernloop.toml"), "review", "dedupe"]), 0)
        self.assertEqual(self.conn.execute("SELECT status FROM claim WHERE id=?", (new_id,)).fetchone()[0],
                         "zurückgezogen")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM conflict WHERE status='offen'").fetchone()[0], 0)

    def test_contradiction_within_one_session_is_recorded(self):
        def responder(step, prompt, schema):
            if step == "abgleich":
                ids = re.findall(r'erkenntnis id="(ERK-\d+)"', prompt)
                return {"befunde": [{"neu": ids[0], "bestehend": ids[1], "art": "widerspricht",
                                     "erklaerung": "Test"}]}
            return good_responder(step, prompt, schema)

        sid, state = run_session(self.cfg, self.conn, self.web, responder)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM conflict WHERE session_id=?", (sid,)).fetchone()[0], 1)
        first = self.conn.execute("SELECT status FROM claim WHERE id='ERK-000001'").fetchone()[0]
        self.assertEqual(first, "widersprüchlich")

    def test_repeat_session_marks_read_pages_and_keeps_partial_status(self):
        run_session(self.cfg, self.conn, self.web, good_responder)  # liest /iterator
        with dbm.Tx(self.conn):
            self.conn.execute("UPDATE goal SET status='teilweise' WHERE id='T01-Z2'")
        seen = []

        def responder(step, prompt, schema):
            if step == "plan":
                return {"bereits_beantwortet": False, "frage": "?", "begruendung": "-",
                        "suchbegriffe_en": ["iterator", "aggregator"]}
            if step == "auswahl":
                seen.append(prompt)
                return {"urls": [], "begruendung": "nichts Neues"}
            if step == "beurteilung":
                return {"ergebnis": "teilweise", "begruendung": "unverändert", "fehlende_information": ["x"],
                        "fehlerklasse": "abrufproblem", "naechste_suchbegriffe_en": ["iterator"]}
            return good_responder(step, prompt, schema)

        sid, _ = run_session(self.cfg, self.conn, self.web, responder)
        self.assertIn("[bereits ausgewertet]", seen[0])
        first_line = [l for l in seen[0].splitlines() if l.startswith("- https://")][0]
        self.assertNotIn("[bereits ausgewertet]", first_line)  # Ungelesenes steht vorne
        self.assertEqual(self.conn.execute("SELECT end_reason FROM session WHERE id=?", (sid,)).fetchone()[0],
                         "kein_fortschritt")
        self.assertEqual(self.conn.execute("SELECT status FROM goal WHERE id='T01-Z2'").fetchone()[0], "teilweise")

    def test_other_goals_are_named_as_out_of_scope(self):
        client = FakeClient(good_responder)
        sess = LearningSession(self.cfg, self.conn, client, fetcher_factory(self.cfg, self.web), log=lambda *a: None)
        sid = sess.create("T01", "T01-Z2")
        sess.load(sid)
        sess.run()
        plan_prompt = next(p for step, p in client.calls if step == "plan")
        self.assertIn("NICHT hier verfolgen", plan_prompt)
        self.assertIn("leeren Arrays", plan_prompt)  # Z5 wird als eigenes Lernziel genannt
        self.assertNotIn("- Wie funktioniert das Iterator-Modul", plan_prompt)  # eigenes Ziel nicht als „anderes“

    def test_nacharbeit_after_retrieval_problem(self):
        calls = []

        def responder(step, prompt, schema):
            calls.append(step)
            if step == "plan":
                return {"bereits_beantwortet": False, "frage": "?", "begruendung": "-", "suchbegriffe_en": ["zzzz"]}
            if step == "beurteilung":
                if calls.count("beurteilung") == 1:
                    return {"ergebnis": "teilweise", "begruendung": "nichts gefunden", "fehlende_information": ["x"],
                            "fehlerklasse": "abrufproblem", "naechste_suchbegriffe_en": ["iterator"]}
            return good_responder(step, prompt, schema)

        sid, state = run_session(self.cfg, self.conn, self.web, responder)
        ctx = json.loads(self.conn.execute("SELECT context FROM session WHERE id=?", (sid,)).fetchone()["context"])
        self.assertEqual(len(ctx["rounds"]), 2)
        self.assertIn("abrufproblem", ctx["error_classes"])
        self.assertEqual(ctx["outcome"], "ziel_erreicht")


class OpenFindingWarningTests(unittest.TestCase):
    def test_narrowing_finding_is_shown_as_warning_when_claim_is_used(self):
        from lernloop import prompts
        cfg, conn, _ = make_env()
        run_session(cfg, conn, FakeWeb(), good_responder)
        with dbm.Tx(conn):
            knowledge.add_conflict(conn, ["ERK-000003", "ERK-000001"], "schraenkt_ein", "zu breit", None)
        claims = knowledge.retrieve_claims(conn, "iterator bundle")
        c1 = next(c for c in claims if c["id"] == "ERK-000001")
        self.assertEqual(c1["status"], "dokumentiert")  # Status bleibt, aber mit Warnung
        self.assertIn("zu breit", c1["offener_befund"])
        self.assertIn("ACHTUNG, offener Befund", prompts.block_claims([c1]))


class ReviewShortcutTests(unittest.TestCase):
    def test_narrow_confirm_and_close_findings_in_one_step(self):
        from lernloop.cli import main
        cfg, conn, _ = make_env()
        run_session(cfg, conn, FakeWeb(), good_responder)
        with dbm.Tx(conn):
            knowledge.add_conflict(conn, ["ERK-000003", "ERK-000001"], "widerspricht", "Test", None)
        self.assertEqual(conn.execute("SELECT status FROM claim WHERE id='ERK-000001'").fetchone()[0],
                         "widersprüchlich")
        with mock.patch("builtins.print"):
            rc = main(["--config", str(cfg.base_dir / "lernloop.toml"), "review", "narrow", "ERK-000003",
                       "--statement", "Engere Fassung", "--reason", "zu breit", "--bestaetigen",
                       "--befunde-schliessen"])
        self.assertEqual(rc, 0)
        new = conn.execute("SELECT id, status FROM claim WHERE supersedes_id='ERK-000003'").fetchone()
        self.assertEqual(new["status"], "dokumentiert")
        self.assertEqual(conn.execute("SELECT status FROM claim WHERE id='ERK-000003'").fetchone()[0], "zurückgezogen")
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM conflict WHERE status='offen'").fetchone()[0], 0)
        # Die Gegenseite war nur wegen des Widerspruchs zurückgehalten → wieder dokumentiert
        self.assertEqual(conn.execute("SELECT status FROM claim WHERE id='ERK-000001'").fetchone()[0], "dokumentiert")


class SectionSelectionTests(unittest.TestCase):
    def test_long_page_keeps_sections_matching_the_question(self):
        from lernloop.session import _relevant_sections
        secs = [{"heading_path": f"Tools > Modul {i}", "text": "x " * 3000} for i in range(10)]
        secs.append({"heading_path": "Tools > Text aggregator", "text": "The Text aggregator joins text. " * 20})
        chosen = _relevant_sections(secs, "text aggregator row separator", 8000)
        self.assertIn("Tools > Text aggregator", [s["heading_path"] for s in chosen])
        self.assertLessEqual(sum(len(s["text"]) for s in chosen), 8000)


class StatusRuleTests(unittest.TestCase):
    def setUp(self):
        self.cfg, self.conn, _ = make_env()
        run_session(self.cfg, self.conn, FakeWeb(), good_responder)
        self.claims = {c["statement"][:15]: c["id"] for c in self.conn.execute("SELECT * FROM claim")}

    def test_practical_confirmation_locked(self):
        with self.assertRaises(knowledge.StatusRuleViolation):
            knowledge.set_status(self.conn, self.claims["Der Iterator gi"], "praktisch_bestätigt", "x", "mensch")

    def test_human_can_confirm_inference_but_not_fabricated_quote(self):
        knowledge.set_status(self.conn, self.claims["Nach dem Iterat"], "dokumentiert", "geprüft", "mensch")
        with self.assertRaises(knowledge.StatusRuleViolation):
            knowledge.set_status(self.conn, self.claims["Der Iterator so"], "dokumentiert", "trotzdem", "mensch")

    def test_reason_required(self):
        with self.assertRaises(knowledge.StatusRuleViolation):
            knowledge.set_status(self.conn, self.claims["Der Iterator gi"], "zurückgezogen", " ", "mensch")

    def test_theoretically_checked_needs_graded_practice(self):
        cid = self.claims["Der Iterator gi"]
        with self.assertRaises(knowledge.StatusRuleViolation):
            knowledge.set_status(self.conn, cid, "theoretisch_geprüft", "x", "programm")
        with dbm.Tx(self.conn):
            self.conn.execute("INSERT INTO task VALUES('AUF-1','übung','T01','vorhersage','?','\"3\"',NULL,'mensch','H',?)",
                              (dbm.now(),))
            self.conn.execute("INSERT INTO attempt(id, task_id, variant, answer, cited_claims, grade_status, passed, "
                              "created_at) VALUES('VER-1','AUF-1','lernen','3',?,'bewertet',1,?)",
                              (json.dumps([cid]), dbm.now()))
        knowledge.set_status(self.conn, cid, "theoretisch_geprüft", "Übung bestanden", "programm")

    def test_retrieval_excludes_retracted(self):
        cid = self.claims["Der Iterator gi"]
        self.assertIn(cid, [c["id"] for c in knowledge.retrieve_claims(self.conn, "iterator bundle")])
        new = knowledge.supersede(self.conn, cid, "Eingeschränkt: nur bei Arrays", None, "zu breit", "mensch")
        ids = [c["id"] for c in knowledge.retrieve_claims(self.conn, "iterator bundle")]
        self.assertNotIn(cid, ids)
        self.assertEqual(self.conn.execute("SELECT supersedes_id FROM claim WHERE id=?", (new,)).fetchone()[0], cid)

    def test_changed_source_marks_claim_stale(self):
        web = FakeWeb()
        web.pages["/iterator"] = (200, "text/html", (FIX / "iterator_v2.html").read_text())
        cid = self.claims["Der Iterator gi"]
        # v2 enthält das Zitat noch → bleibt gültig
        f = Fetcher(self.cfg.section("fetch"), self.conn, transport=web.transport, resolver=resolver_public,
                    sleep=lambda s: None)
        res = f.fetch("https://help.make.com/iterator")
        with dbm.Tx(self.conn):
            knowledge.store_page(self.conn, self.cfg, res, parse_html(res.text, res.final_url), None)
        self.assertEqual(self.conn.execute("SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0], "dokumentiert")
        # v3 ohne das Zitat → veraltet
        web.pages["/iterator"] = (200, "text/html", "<html><body><h1>Iterator</h1><p>Völlig neuer Text ohne Zitat hier.</p></body></html>")
        res = f.fetch("https://help.make.com/iterator")
        with dbm.Tx(self.conn):
            knowledge.store_page(self.conn, self.cfg, res, parse_html(res.text, res.final_url), None)
        self.assertEqual(self.conn.execute("SELECT status FROM claim WHERE id=?", (cid,)).fetchone()[0], "veraltet")


class AskTests(unittest.TestCase):
    def test_invalid_citations_are_rejected(self):
        from lernloop.ask import answer
        cfg, conn, _ = make_env()
        web = FakeWeb()
        run_session(cfg, conn, web, good_responder)
        res = answer(cfg, conn, FakeClient(good_responder), fetcher_factory(cfg, web), "Was macht der Iterator?",
                     log=lambda *a: None)
        self.assertIn("ERK-999999", res["ungültige_belege"])
        self.assertTrue(res["belege"])
        res_a = answer(cfg, conn, FakeClient(good_responder), fetcher_factory(cfg, web), "Was macht der Iterator?",
                       variant="A", log=lambda *a: None)
        self.assertEqual(res_a["genutzte_erkenntnisse"], [])


class TomlFallbackTests(unittest.TestCase):
    def test_fallback_parser_matches_config_files(self):
        from lernloop import _toml
        root = Path(__file__).parent.parent
        for f in ("config/limits.example.toml", "lernloop/topics.toml"):
            parsed = _toml.loads((root / f).read_text(encoding="utf-8"))
            self.assertIn("paths" if "limits" in f else "topic", parsed)
        s = 'a = "x # y" # k\n[t]\nb = [1, 2_000, 3.5]\nc = { "h" = ["/p"] }\n[[arr]]\nx = 1\n[[arr]]\nx = 2\n'
        self.assertEqual(_toml.loads(s), {"a": "x # y", "t": {"b": [1, 2000, 3.5], "c": {"h": ["/p"]}},
                                          "arr": [{"x": 1}, {"x": 2}]})


class LockTests(unittest.TestCase):
    def test_second_session_refused_and_stale_lock_taken_over(self):
        cfg, _, tmp = make_env()
        with SessionLock(cfg.lock_path, "a"):
            with self.assertRaises(LockHeld):
                with SessionLock(cfg.lock_path, "b"):
                    pass
        cfg.lock_path.write_text(json.dumps({"pid": 999999, "purpose": "alt"}))
        with SessionLock(cfg.lock_path, "c") as lock:
            self.assertEqual(lock.stale_previous["purpose"], "alt")
        self.assertFalse(cfg.lock_path.exists())


class ClaudeCodeTests(unittest.TestCase):
    def test_args_disable_tools_and_env_strips_api_key(self):
        client = model.ClaudeCodeClient({"claude_code_model": "opus"})
        args = client.build_args("SYS", {"type": "object"})
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertIn("--strict-mcp-config", args)
        self.assertIn("--no-session-persistence", args)
        captured = {}

        def fake_run(cmd, **kw):
            captured.update(kw)
            return subprocess.CompletedProcess(cmd, 0, json.dumps(
                {"type": "result", "is_error": False, "result": "", "structured_output": {"ok": True},
                 "usage": {"input_tokens": 10, "output_tokens": 3}, "modelUsage": {"claude-opus-x": {}}}), "")

        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-geheim"}), \
                mock.patch("shutil.which", return_value="/usr/bin/claude"), \
                mock.patch("subprocess.run", fake_run):
            res = client.complete("SYS", "prompt", {"type": "object"}, "t")
        self.assertNotIn("ANTHROPIC_API_KEY", captured["env"])
        self.assertEqual(captured["input"], "prompt")
        self.assertEqual(res.data, {"ok": True})
        self.assertEqual(res.model, "claude-opus-x")

    def test_parse_outputs(self):
        ok = parse_claude_output(0, json.dumps({"is_error": False, "result": "```json\n{\"a\": 1}\n```"}), "", 5)
        self.assertEqual(ok.data, {"a": 1})
        with self.assertRaises(UsageLimitReached):
            parse_claude_output(1, json.dumps({"is_error": True, "result": "Claude AI usage limit reached|1760000000"}), "", 5)
        with self.assertRaises(ModelError):
            parse_claude_output(1, "", "Invalid API key · Please run /login", 5)
        with self.assertRaises(ModelError) as ctx:
            parse_claude_output(1, json.dumps({"is_error": True, "result": "Failed to authenticate. API Error: 401 "
                                               "OAuth access token has expired. Re-authenticate to continue."}), "", 5)
        self.assertIn("/login", str(ctx.exception))


class BackupTests(unittest.TestCase):
    def test_backup_restore_roundtrip_and_checksum(self):
        cfg, conn, _ = make_env()
        run_session(cfg, conn, FakeWeb(), good_responder)
        before = conn.execute("SELECT COUNT(*) FROM claim").fetchone()[0]
        path = exporter.backup(conn, cfg)
        with dbm.Tx(conn):
            conn.execute("DELETE FROM claim_history")
            conn.execute("DELETE FROM evidence")
            conn.execute("DELETE FROM claim")
        conn.close()
        exporter.restore(cfg, path)
        conn2 = dbm.connect(cfg.db_path)
        self.assertEqual(conn2.execute("SELECT COUNT(*) FROM claim").fetchone()[0], before)
        out = exporter.export_jsonl(conn2, cfg)
        self.assertTrue((out / "claim.jsonl").read_text().strip())
        path.write_bytes(path.read_bytes() + b"x")
        with self.assertRaises(ValueError):
            exporter.restore(cfg, path)

    def test_read_only_connection_cannot_write(self):
        cfg, conn, _ = make_env()
        ro = dbm.connect(cfg.db_path, read_only=True)
        with self.assertRaises(sqlite3.OperationalError):
            ro.execute("INSERT INTO meta(key, value) VALUES('x','y')")

    def test_paths_confined_to_project(self):
        cfg, _, _ = make_env()
        from lernloop.config import PathOutsideProject
        with self.assertRaises(PathOutsideProject):
            cfg.safe_path("..", "..", "etc", "passwd")


if __name__ == "__main__":
    unittest.main()
