"""Eine Lernsitzung als Zustandsautomat mit Checkpoints (Brief §6).

Jeder Schritt schreibt seinen Stand in die Datenbank. Eine unterbrochene Sitzung
(Nutzungslimit, Strg+C, Absturz) kann mit ``--resume`` am letzten Checkpoint fortgesetzt
werden. Neue Erkenntnisse bleiben bis zum Festschreiben Entwürfe.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from . import catalog, knowledge, prompts
from . import db as dbm
from .extract import parse_html
from .fetcher import FetchFailed, FetchRefused
from .model import ModelError, UsageLimitReached, validate

TERMINAL = "ABGESCHLOSSEN"


class LimitReached(Exception):
    """Sitzungslimit erreicht → Sitzung wird mit dem bisherigen Stand abgeschlossen."""


class PauseSession(Exception):
    """Sitzung pausieren (Abo-Nutzungslimit, Tageslimit, Fehler) → später fortsetzen."""


class Limits:
    def __init__(self, cfg, conn, session_id: str, backend: str):
        self.s = cfg.section("session")
        self.daily = int(cfg.section("subscription_limits")["max_calls_per_day"])
        self.conn = conn
        self.session_id = session_id
        self.backend = backend
        self.run_started = time.monotonic()
        row = conn.execute("SELECT active_seconds FROM session WHERE id=?", (session_id,)).fetchone()
        self.base_seconds = row["active_seconds"] if row else 0.0

    def elapsed(self) -> float:
        return self.base_seconds + (time.monotonic() - self.run_started)

    def model_calls(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM model_call WHERE session_id=?", (self.session_id,)).fetchone()[0]

    def fetches(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM fetch_log WHERE session_id=?", (self.session_id,)).fetchone()[0]

    def calls_today(self) -> int:
        start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.conn.execute(
            "SELECT COUNT(*) FROM model_call WHERE backend=? AND created_at >= ?",
            (self.backend, start.astimezone(timezone.utc).isoformat(timespec="seconds"))).fetchone()[0]

    def check_time(self) -> None:
        if self.elapsed() >= self.s["max_duration_minutes"] * 60:
            raise LimitReached(f"Laufzeitlimit ({self.s['max_duration_minutes']} Min.) erreicht")

    def before_model_call(self) -> None:
        self.check_time()
        if self.model_calls() >= self.s["max_model_calls"]:
            raise LimitReached(f"Limit Modellaufrufe je Sitzung ({self.s['max_model_calls']}) erreicht")
        if self.backend == "claude_code" and self.calls_today() >= self.daily:
            raise PauseSession(f"Tageslimit ({self.daily} Aufrufe) erreicht – morgen mit --resume fortsetzen")

    def before_fetch(self) -> None:
        self.check_time()
        if self.fetches() >= self.s["max_page_fetches"]:
            raise LimitReached(f"Limit Seitenabrufe je Sitzung ({self.s['max_page_fetches']}) erreicht")


class ModelCaller:
    """Modellaufruf mit Limitprüfung, Schemaprüfung (1 Wiederholung) und Protokoll."""

    def __init__(self, cfg, conn, client, session_id, before_call, log=print):
        self.cfg, self.conn, self.client = cfg, conn, client
        self.session_id, self.before_call, self.log = session_id, before_call, log

    def call(self, step: str, prompt: str, schema: dict) -> dict:
        last_error = None
        for attempt in range(2):
            self.before_call()
            full = prompt if attempt == 0 else (
                prompt + f"\n\nDeine vorige Antwort war ungültig: {last_error}. Antworte nur mit gültigem JSON nach Schema.")
            try:
                res = self.client.complete(prompts.SYSTEM, full, schema, step)
            except ModelError as exc:
                self._record(step, None, False, str(exc), full, None)
                raise
            errors = validate(schema, res.data)
            mid = self._record(step, res, not errors, "; ".join(errors) or None, full, res.raw_text)
            if not errors:
                return res.data
            last_error = "; ".join(errors[:5])
            self.log(f"  Antwort {mid} verletzt das Schema: {last_error}")
        raise ModelError(f"Antwort im Schritt {step} zweimal ungültig: {last_error}")

    def _record(self, step, res, ok, error, prompt, response) -> str:
        mid = dbm.new_id(self.conn, "model_call")
        log_path = self.cfg.safe_path("logs", "calls", f"{mid}.json")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps({"id": mid, "session": self.session_id, "step": step, "prompt": prompt,
                                        "response": response, "error": error}, ensure_ascii=False, indent=1),
                            encoding="utf-8")
        self.conn.execute(
            "INSERT INTO model_call(id, session_id, step, backend, model, input_tokens, output_tokens, "
            "cache_read_tokens, cost_usd_equiv, duration_ms, ok, error, log_path, created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (mid, self.session_id, step, self.client.backend, res.model if res else None,
             res.input_tokens if res else None, res.output_tokens if res else None,
             res.cache_read_tokens if res else None, res.cost_usd_equiv if res else None,
             res.duration_ms if res else None, int(ok), error, str(log_path.relative_to(self.cfg.data_dir)),
             dbm.now()))
        return mid


class LearningSession:
    def __init__(self, cfg, conn, client, fetcher_factory, log=print):
        self.cfg = cfg
        self.conn = conn
        self.client = client
        self.fetcher_factory = fetcher_factory
        self.log = log
        self.sid: str | None = None
        self.ctx: dict = {}
        self.limits: Limits | None = None
        self.fetcher = None

    # --- Anlegen / Fortsetzen -----------------------------------------------------------
    def create(self, topic_id: str, goal_id: str | None = None) -> str:
        if not self.cfg.section("fetch").get("terms_reviewed"):
            from .fetcher import TERMS_MESSAGE
            raise ValueError(TERMS_MESSAGE)
        topic = self.conn.execute("SELECT * FROM topic WHERE id=?", (topic_id,)).fetchone()
        if not topic:
            raise ValueError(f"Thema {topic_id} nicht gefunden (lernloop plan show)")
        if goal_id:
            goal = self.conn.execute("SELECT * FROM goal WHERE id=? AND topic_id=?", (goal_id, topic_id)).fetchone()
        else:
            goal = self.conn.execute(
                "SELECT * FROM goal WHERE topic_id=? AND status IN ('offen','teilweise') ORDER BY "
                "CASE status WHEN 'offen' THEN 0 ELSE 1 END, ord LIMIT 1", (topic_id,)).fetchone()
        if not goal:
            raise ValueError("Kein offenes Lernziel in diesem Thema (lernloop plan show)")
        with dbm.Tx(self.conn):
            sid = dbm.new_id(self.conn, "session")
            ctx = {"round": 1, "rounds_without_progress": 0, "fetched_urls": [], "rounds": [],
                   "session_claims": [], "outcome": None, "error_classes": []}
            self.conn.execute(
                "INSERT INTO session(id, topic_id, goal_id, state, started_at, limits_snapshot, context) "
                "VALUES(?,?,?,?,?,?,?)",
                (sid, topic_id, goal["id"], "ZIEL_GEWÄHLT", dbm.now(),
                 json.dumps({"session": self.cfg.section("session"),
                             "subscription_limits": self.cfg.section("subscription_limits"),
                             "model": {k: v for k, v in self.cfg.section("model").items()}}, ensure_ascii=False),
                 json.dumps(ctx, ensure_ascii=False)))
            self.conn.execute("UPDATE goal SET status='in_arbeit', updated_at=? WHERE id=?", (dbm.now(), goal["id"]))
        return sid

    def load(self, sid: str) -> None:
        row = self.conn.execute("SELECT * FROM session WHERE id=?", (sid,)).fetchone()
        if not row:
            raise ValueError(f"Sitzung {sid} nicht gefunden")
        if row["state"] == TERMINAL:
            raise ValueError(f"Sitzung {sid} ist bereits abgeschlossen ({row['end_reason']})")
        if not self.cfg.section("fetch").get("terms_reviewed"):
            from .fetcher import TERMS_MESSAGE
            raise ValueError(TERMS_MESSAGE)
        self.sid = sid
        self.ctx = json.loads(row["context"])
        self.limits = Limits(self.cfg, self.conn, sid, self.client.backend)
        self.fetcher = self.fetcher_factory(self.conn, sid, self.limits.before_fetch)
        self.caller = ModelCaller(self.cfg, self.conn, self.client, sid, self.limits.before_model_call, self.log)

    @property
    def row(self):
        return self.conn.execute("SELECT * FROM session WHERE id=?", (self.sid,)).fetchone()

    def checkpoint(self, state: str | None = None, **fields) -> None:
        sets = {"context": json.dumps(self.ctx, ensure_ascii=False), "active_seconds": self.limits.elapsed()}
        if state:
            sets["state"] = state
        sets.update(fields)
        cols = ", ".join(f"{k}=?" for k in sets)
        self.conn.execute(f"UPDATE session SET {cols} WHERE id=?", (*sets.values(), self.sid))
        self.limits.base_seconds = sets["active_seconds"]
        self.limits.run_started = time.monotonic()

    # --- Hauptschleife -----------------------------------------------------------------
    def run(self) -> str:
        """Führt die Sitzung bis zum Abschluss oder zur Pause. Liefert den Endzustand."""
        self.conn.execute("UPDATE session SET paused_reason=NULL WHERE id=?", (self.sid,))
        steps = {
            "ZIEL_GEWÄHLT": self._step_prior,
            "VORWISSEN_GELADEN": self._step_plan,
            "FRAGE_FORMULIERT": self._step_research,
            "RECHERCHIERT": self._step_extract,
            "AUSSAGEN_ERFASST": self._step_compare,
            "ABGEGLICHEN": self._step_assess,
            "ÜBUNG": self._step_practice,
            "FESTSCHREIBEN": self._step_commit,
        }
        try:
            while True:
                state = self.row["state"]
                if state == TERMINAL:
                    return TERMINAL
                try:
                    steps[state]()
                except LimitReached as exc:
                    self.log(f"  Limit: {exc}")
                    self.ctx["outcome"] = self.ctx.get("outcome") or "limit_erreicht"
                    self.ctx["limit_detail"] = str(exc)
                    self.checkpoint("FESTSCHREIBEN")
                    self._step_commit()
                    return TERMINAL
        except UsageLimitReached as exc:
            return self._pause(f"Nutzungslimit des Claude-Abos erreicht: {exc}")
        except PauseSession as exc:
            return self._pause(str(exc))
        except ModelError as exc:
            return self._pause(f"Modellfehler: {exc}")
        except FetchRefused as exc:
            return self._pause(f"Abruf verweigert: {exc}")
        except KeyboardInterrupt:
            return self._pause("abgebrochen_durch_nutzer")

    def _pause(self, reason: str) -> str:
        self.checkpoint(paused_reason=reason)
        self.log(f"  Sitzung pausiert: {reason}")
        self.log(f"  Fortsetzen mit: lernloop learn --resume {self.sid}")
        return "PAUSIERT"

    def call(self, step: str, prompt: str, schema: dict) -> dict:
        return self.caller.call(step, prompt, schema)

    # --- Hilfen ------------------------------------------------------------------------
    def _goal(self):
        return self.conn.execute("SELECT * FROM goal WHERE id=?", (self.row["goal_id"],)).fetchone()

    def _preferred_hosts(self) -> list[str]:
        topic = self._topic()
        try:
            return json.loads(topic["preferred_hosts"] or "[]")
        except (IndexError, KeyError, ValueError):
            return []

    def _topic(self):
        return self.conn.execute("SELECT * FROM topic WHERE id=?", (self.row["topic_id"],)).fetchone()

    def _cur_round(self) -> dict:
        if not self.ctx["rounds"] or self.ctx["rounds"][-1]["nr"] != self.ctx["round"]:
            self.ctx["rounds"].append({"nr": self.ctx["round"], "question": None, "terms": [], "candidates": [],
                                       "selected": [], "sources": [], "extracted": [], "claims": [],
                                       "rejected": [], "open_points": [], "assessment": None})
        return self.ctx["rounds"][-1]

    def _claims(self, ids):
        if not ids:
            return []
        return self.conn.execute(f"SELECT * FROM claim WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall()

    def _verified_session_claims(self):
        return [c for c in self._claims(self.ctx["session_claims"])
                if c["status"] not in ("zurückgezogen",) and self.conn.execute(
                    "SELECT COUNT(*) FROM evidence WHERE claim_id=? AND verified_quote=1", (c["id"],)).fetchone()[0]]

    # --- Schritte ----------------------------------------------------------------------
    def _step_prior(self) -> None:
        goal = self._goal()
        prior = knowledge.retrieve_claims(self.conn, goal["text"], goal_id=goal["id"])
        oq = [r["text"] for r in self.conn.execute(
            "SELECT text FROM open_question WHERE goal_id=? AND status='offen'", (goal["id"],))]
        conflicts = [r["description"] for r in knowledge.open_conflicts(self.conn, self.row["topic_id"])]
        self.ctx["prior_claims"] = [c["id"] for c in prior]
        self.ctx["prior_open_questions"] = oq
        self.ctx["prior_conflicts"] = conflicts
        self.log(f"Lernziel: {goal['text']}")
        self.log(f"  Vorwissen: {len(prior)} Erkenntnisse, {len(oq)} offene Fragen, {len(conflicts)} Widersprüche")
        self.checkpoint("VORWISSEN_GELADEN")

    def _step_plan(self) -> None:
        goal, topic = self._goal(), self._topic()
        prior = self._claims(self.ctx.get("prior_claims", []))
        data = self.call("plan", prompts.plan_prompt(topic["title"], goal["text"], prior,
                                                     self.ctx.get("prior_open_questions"),
                                                     self.ctx.get("prior_conflicts")), prompts.PLAN_SCHEMA)
        rnd = self._cur_round()
        if data["bereits_beantwortet"] and prior:
            self.log("  Laut Vorwissen bereits beantwortet.")
            rnd["assessment"] = {"ergebnis": "beantwortet", "begruendung": data["begruendung"],
                                 "fehlende_information": [], "fehlerklasse": "keine", "naechste_suchbegriffe_en": []}
            self.ctx["outcome"] = "ziel_erreicht"
            self.checkpoint("ÜBUNG")
            return
        rnd["question"] = data["frage"]
        rnd["terms"] = data["suchbegriffe_en"] or [goal["text"]]
        self.ctx["question"] = data["frage"]
        with dbm.Tx(self.conn):
            self.conn.execute(
                "INSERT INTO open_question(id, goal_id, text, status, session_id, created_at) VALUES(?,?,?,?,?,?)",
                (dbm.new_id(self.conn, "open_question"), goal["id"], data["frage"], "offen", self.sid, dbm.now()))
        self.log(f"  Frage: {data['frage']}")
        self.log(f"  Suchbegriffe: {', '.join(rnd['terms'])}")
        self.checkpoint("FRAGE_FORMULIERT")

    def _step_research(self) -> None:
        rnd = self._cur_round()
        s = self.cfg.section("session")
        if not rnd["candidates"]:
            if catalog.count(self.conn) == 0:
                self.log("  Seitenkatalog ist leer – wird aus den Sitemaps aufgebaut …")
                catalog.refresh_from_sitemaps(self.conn, self.fetcher, log=lambda m: self.log(m))
            rnd["candidates"] = catalog.search(self.conn, rnd["terms"], limit=15,
                                               exclude=set(self.ctx["fetched_urls"]),
                                               prefer_hosts=self._preferred_hosts())
            self.checkpoint()
        if not rnd["candidates"]:
            self.log("  Keine passenden Seiten im Katalog gefunden.")
            self.ctx["error_classes"].append("abrufproblem")
            self.checkpoint("RECHERCHIERT")
            return
        if not rnd["selected"]:
            data = self.call("auswahl", prompts.select_prompt(rnd["question"] or self.ctx.get("question"),
                                                              rnd["candidates"]), prompts.SELECT_SCHEMA)
            allowed = {c["url"] for c in rnd["candidates"]}
            chosen = [u for u in data["urls"] if u in allowed][: int(s["max_pages_per_round"])]
            dropped = [u for u in data["urls"] if u not in allowed]
            if dropped:
                self.log(f"  Verworfen (nicht in der Kandidatenliste): {dropped}")
            rnd["selected"] = chosen or ["-"]
            self.checkpoint()
        for url in rnd["selected"]:
            if url == "-" or url in self.ctx["fetched_urls"]:
                continue
            self.log(f"  Abruf: {url}")
            try:
                res = self.fetcher.fetch(url)
            except (FetchRefused, FetchFailed) as exc:
                self.log(f"    nicht abgerufen: {exc}")
                self.ctx["fetched_urls"].append(url)
                self.checkpoint()
                continue
            if res.status != 200:
                self.log(f"    HTTP {res.status}")
                self.ctx["fetched_urls"].append(url)
                self.checkpoint()
                continue
            page = parse_html(res.text, res.final_url)
            with dbm.Tx(self.conn):
                source_id, _ = knowledge.store_page(self.conn, self.cfg, res, page, self.sid)
                catalog.add_page(self.conn, res.final_url, page.title, "abruf")
                catalog.add_links(self.conn, page.links, self.fetcher.policy, f"link:{res.final_url}")
            rnd["sources"].append(source_id)
            self.ctx["fetched_urls"].append(url)
            self.log(f"    gespeichert als {source_id}: {page.title} ({len(page.sections)} Abschnitte)")
            self.checkpoint()
        self.checkpoint("RECHERCHIERT")

    def _step_extract(self) -> None:
        rnd = self._cur_round()
        goal = self._goal()
        max_chars = int(self.cfg.section("session")["max_chars_per_page"])
        for source_id in rnd["sources"]:
            if source_id in rnd["extracted"]:
                continue
            src = self.conn.execute("SELECT * FROM source WHERE id=?", (source_id,)).fetchone()
            sections = knowledge.sections_of(self.conn, source_id)
            block = prompts.block_sections(src["title"] or "", src["final_url"], sections, max_chars)
            known = self._verified_session_claims() + self._claims(self.ctx.get("prior_claims", []))
            data = self.call("extraktion", prompts.extract_prompt(rnd["question"] or self.ctx.get("question"),
                                                                  goal["text"], block, known[:40]),
                             prompts.EXTRACT_SCHEMA)
            allowed = {s["id"] for s in sections}
            n_ok = 0
            with dbm.Tx(self.conn):
                for item in data["aussagen"]:
                    cid, ok = knowledge.add_claim(self.conn, self.sid, self.row["topic_id"], goal["id"], item, allowed)
                    rnd["claims"].append(cid)
                    self.ctx["session_claims"].append(cid)
                    if ok:
                        n_ok += 1
                    else:
                        rnd["rejected"].append(item.get("zitat", "")[:200])
            rnd["open_points"].extend(data["offene_punkte"])
            rnd["extracted"].append(source_id)
            self.log(f"  {source_id}: {len(data['aussagen'])} Aussagen, davon {n_ok} mit wörtlich gefundenem Zitat")
            self.checkpoint()
        self.checkpoint("AUSSAGEN_ERFASST")

    def _step_compare(self) -> None:
        """Neue Aussagen gegen Bestand UND frühere Runden dieser Sitzung abgleichen."""
        rnd = self._cur_round()
        new = self._claims(rnd["claims"])
        if new:
            text = " ".join(f"{c['statement']} {c['keywords'] or ''}" for c in new)
            new_ids = {c["id"] for c in new}
            existing = [c for c in knowledge.retrieve_claims(self.conn, text, limit=15)
                        if c["id"] not in self.ctx["session_claims"]]
            earlier = [c for c in self._verified_session_claims() if c["id"] not in new_ids]
            candidates = existing + earlier
            # Auch innerhalb der aktuellen Runde können sich Aussagen verschiedener Seiten widersprechen.
            if len(new) > 1 or candidates:
                data = self.call("abgleich", prompts.compare_prompt(new, candidates or new), prompts.COMPARE_SCHEMA)
                old_ids = {c["id"] for c in candidates} or new_ids
                with dbm.Tx(self.conn):
                    for b in data["befunde"]:
                        if b["neu"] in new_ids and b["bestehend"] in old_ids and b["neu"] != b["bestehend"]:
                            kid = knowledge.add_conflict(self.conn, [b["neu"], b["bestehend"]], b["art"],
                                                         b["erklaerung"], self.sid)
                            self.log(f"  Befund {kid} ({b['art']}): {b['neu']} ↔ {b['bestehend']}")
        self.checkpoint("ABGEGLICHEN")

    def _step_assess(self) -> None:
        rnd = self._cur_round()
        s = self.cfg.section("session")
        goal = self._goal()
        verified = self._verified_session_claims() + self._claims(self.ctx.get("prior_claims", []))
        data = self.call("beurteilung", prompts.assess_prompt(goal["text"], rnd["question"] or self.ctx.get("question"),
                                                              verified, rnd["open_points"], rnd["rejected"]),
                         prompts.ASSESS_SCHEMA)
        rnd["assessment"] = data
        if data["fehlerklasse"] != "keine":
            self.ctx["error_classes"].append(data["fehlerklasse"])
        new_verified = [c for c in rnd["claims"] if c in {v["id"] for v in verified}]
        if new_verified:
            self.ctx["rounds_without_progress"] = 0
        else:
            self.ctx["rounds_without_progress"] += 1
        self.log(f"  Beurteilung: {data['ergebnis']} ({data['fehlerklasse']}) – {data['begruendung']}")

        if data["ergebnis"] == "beantwortet":
            self.ctx["outcome"] = "ziel_erreicht"
            self.checkpoint("ÜBUNG")
            return
        sources_read = sum(len(r["extracted"]) for r in self.ctx["rounds"])
        if data["ergebnis"] == "nicht_belegbar" and sources_read == 0:
            # Programmregel: Ohne gelesene Quelle ist „nicht belegbar“ nicht festgestellt – das ist ein Abrufproblem.
            self.log("  Programmregel: ohne gelesene Quelle gilt „nicht belegbar“ nicht – wird als Abrufproblem behandelt.")
            data["ergebnis"] = "teilweise"
            data["fehlerklasse"] = "abrufproblem"
            if "abrufproblem" not in self.ctx["error_classes"]:
                self.ctx["error_classes"].append("abrufproblem")
        if data["ergebnis"] == "nicht_belegbar":
            self.ctx["outcome"] = "beweislage_fehlt"
            self.checkpoint("ÜBUNG")
            return
        if self.ctx["rounds_without_progress"] >= s["max_rounds_without_progress"]:
            self.ctx["outcome"] = "kein_fortschritt"
            self.checkpoint("ÜBUNG")
            return
        if self.ctx["round"] >= s["max_rounds"]:
            self.ctx["outcome"] = "limit_erreicht"
            self.ctx["limit_detail"] = f"Maximale Rundenzahl ({s['max_rounds']}) erreicht"
            self.checkpoint("ÜBUNG")
            return
        # Gezielte Nacharbeit – abhängig von der Fehlerklasse.
        prev = rnd
        self.ctx["round"] += 1
        nxt = self._cur_round()
        nxt["question"] = "; ".join(data["fehlende_information"]) or prev["question"]
        if data["fehlerklasse"] == "anwendungsfehler" and prev["rejected"] and not prev.get("reextracted"):
            # Zitate falsch erfasst → dieselben Quellen erneut auswerten, nicht neu recherchieren.
            nxt["sources"] = list(prev["sources"])
            nxt["reextracted"] = True
            self.log("  Nacharbeit: dieselben Quellen erneut auswerten (Zitate waren nicht wörtlich).")
            self.checkpoint("RECHERCHIERT")
            return
        nxt["terms"] = data["naechste_suchbegriffe_en"] or prev["terms"]
        self.log(f"  Nacharbeit Runde {self.ctx['round']}: {nxt['question']}")
        self.checkpoint("FRAGE_FORMULIERT")

    def _step_practice(self) -> None:
        tasks = self.conn.execute(
            "SELECT * FROM task WHERE pool='übung' AND topic_id=? AND id NOT IN "
            "(SELECT task_id FROM attempt WHERE session_id=?) ORDER BY created_at LIMIT 3",
            (self.row["topic_id"], self.sid)).fetchall()
        if not tasks:
            self.ctx["practice_note"] = ("Keine fachlich bestätigten Übungsaufgaben für dieses Thema vorhanden "
                                         "(Entscheidung E1) – Erkenntnisse bleiben höchstens „dokumentiert“.")
            self.checkpoint("FESTSCHREIBEN")
            return
        for t in tasks:
            claims = self._verified_session_claims() + list(knowledge.retrieve_claims(self.conn, t["prompt"]))
            data = self.call("übung", prompts.practice_prompt(t["prompt"], claims), prompts.PRACTICE_SCHEMA)
            known = {c["id"] for c in claims}
            cited = [c for c in data["genutzte_erkenntnisse"] if c in known]
            with dbm.Tx(self.conn):
                self.conn.execute(
                    "INSERT INTO attempt(id, task_id, session_id, variant, answer, cited_claims, grade_status, created_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (dbm.new_id(self.conn, "attempt"), t["id"], self.sid, "lernen",
                     data["antwort"] + ("\n[als offen gekennzeichnet]" if data["offen"] else ""),
                     json.dumps(cited), "offen", dbm.now()))
            self.log(f"  Übung {t['id']} beantwortet – wartet auf Bewertung (lernloop review)")
        self.checkpoint("FESTSCHREIBEN")

    def _step_commit(self) -> None:
        goal = self._goal()
        outcome = self.ctx.get("outcome") or "limit_erreicht"
        last = next((r["assessment"] for r in reversed(self.ctx["rounds"]) if r.get("assessment")), None)
        with dbm.Tx(self.conn):
            summary = knowledge.finalize_session_claims(self.conn, self.sid)
            if outcome == "ziel_erreicht":
                goal_status = "beantwortet"
            elif outcome == "beweislage_fehlt":
                goal_status = "ungeklärt"
            else:
                goal_status = "teilweise" if summary["dokumentiert"] else "offen"
            reason = (last or {}).get("begruendung") or self.ctx.get("limit_detail") or outcome
            self.conn.execute("UPDATE goal SET status=?, status_reason=?, updated_at=? WHERE id=?",
                              (goal_status, reason, dbm.now(), goal["id"]))
            if goal_status == "beantwortet":
                self.conn.execute("UPDATE open_question SET status='beantwortet' WHERE goal_id=? AND status='offen'",
                                  (goal["id"],))
            for missing in (last or {}).get("fehlende_information", []):
                self.conn.execute(
                    "INSERT INTO open_question(id, goal_id, text, status, session_id, created_at) VALUES(?,?,?,?,?,?)",
                    (dbm.new_id(self.conn, "open_question"), goal["id"], missing,
                     "ungeklärt" if outcome == "beweislage_fehlt" else "offen", self.sid, dbm.now()))
            self.ctx["commit_summary"] = summary
            self.checkpoint(TERMINAL, end_reason=outcome, end_detail=self.ctx.get("limit_detail") or reason,
                            ended_at=dbm.now())
        self.log(f"Sitzung {self.sid} abgeschlossen: {outcome}")
        self.log(f"  dokumentiert: {len(summary['dokumentiert'])}, widersprüchlich: {len(summary['widersprüchlich'])}, "
                 f"bleibt Entwurf: {len(summary['bleibt_entwurf'])}")


def unfinished_sessions(conn):
    return conn.execute("SELECT * FROM session WHERE state != ? ORDER BY started_at", (TERMINAL,)).fetchall()


def discard_session(conn, sid: str, reason: str) -> None:
    """Unfertige Sitzung beenden, ohne irgendetwas hochzustufen. Entwürfe bleiben Entwürfe."""
    with dbm.Tx(conn):
        row = conn.execute("SELECT * FROM session WHERE id=?", (sid,)).fetchone()
        conn.execute("UPDATE session SET state=?, end_reason=?, end_detail=?, ended_at=? WHERE id=?",
                     (TERMINAL, reason, "Verworfen; Entwürfe wurden nicht hochgestuft", dbm.now(), sid))
        conn.execute("UPDATE claim SET status_reason='Bleibt Entwurf: Sitzung wurde nicht regulär abgeschlossen' "
                     "WHERE session_id=? AND status='entwurf'", (sid,))
        if row:
            conn.execute("UPDATE goal SET status=CASE WHEN status='in_arbeit' THEN 'offen' ELSE status END WHERE id=?",
                         (row["goal_id"],))
