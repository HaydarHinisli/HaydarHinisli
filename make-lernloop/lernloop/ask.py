"""Eine Frage beantworten – Variante A (nur Dokumentationssuche) oder B (zusätzlich Lernspeicher)."""

from __future__ import annotations

from datetime import datetime, timezone

from . import catalog, knowledge, prompts
from . import db as dbm
from .extract import parse_html
from .fetcher import FetchFailed, FetchRefused
from .session import ModelCaller, PauseSession


def answer(cfg, conn, client, fetcher_factory, question: str, variant: str = "B",
           max_fetches: int = 3, log=print) -> dict:
    daily = int(cfg.section("subscription_limits")["max_calls_per_day"])

    def before_call():
        start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        n = conn.execute("SELECT COUNT(*) FROM model_call WHERE backend=? AND created_at >= ?",
                         (client.backend, start.astimezone(timezone.utc).isoformat(timespec="seconds"))).fetchone()[0]
        if client.backend == "claude_code" and n >= daily:
            raise PauseSession(f"Tageslimit ({daily} Aufrufe) erreicht")

    fetch_count = {"n": 0}

    def before_fetch():
        if fetch_count["n"] >= max_fetches:
            raise FetchRefused("Abruflimit für diese Frage erreicht")
        fetch_count["n"] += 1

    caller = ModelCaller(cfg, conn, client, None, before_call, log)
    terms = caller.call("frage_suchbegriffe", prompts.ask_terms_prompt(question), prompts.ASK_TERMS_SCHEMA)["suchbegriffe_en"]
    text = question + " " + " ".join(terms)

    claims = []
    if variant == "B":
        claims = [c for c in knowledge.retrieve_claims(conn, text, limit=12)
                  if c["status"] in ("dokumentiert", "theoretisch_geprüft", "widersprüchlich", "ungeklärt")]

    sections = list(knowledge.retrieve_sections(conn, text, limit=8))
    if len(sections) < 3 and cfg.section("fetch").get("terms_reviewed"):
        fetcher = fetcher_factory(conn, None, before_fetch)
        for cand in catalog.search(conn, terms, limit=2):
            try:
                res = fetcher.fetch(cand["url"])
            except (FetchRefused, FetchFailed) as exc:
                log(f"  nicht abgerufen: {cand['url']} ({exc})")
                continue
            if res.status == 200:
                page = parse_html(res.text, res.final_url)
                with dbm.Tx(conn):
                    knowledge.store_page(conn, cfg, res, page, None)
                    catalog.add_links(conn, page.links, fetcher.policy, f"link:{res.final_url}")
        sections = list(knowledge.retrieve_sections(conn, text, limit=8))

    blocks = []
    by_source: dict[str, list] = {}
    for s in sections:
        by_source.setdefault(s["source_url"], []).append(s)
    for url, secs in by_source.items():
        blocks.append(prompts.block_sections(secs[0]["source_title"] or "", url, secs, 8000))

    data = caller.call("antwort", prompts.answer_prompt(question, claims, "\n".join(blocks)), prompts.ANSWER_SCHEMA)
    provided = {c["id"] for c in claims} | {s["id"] for s in sections}
    valid = [b for b in data["belege"] if b in provided]
    invalid = [b for b in data["belege"] if b not in provided]
    return {
        "variante": variant,
        "antwort": data["antwort"],
        "offen": data["offen"],
        "belege": valid,
        "ungültige_belege": invalid,
        "unbelegte_teile": data["unbelegte_teile"],
        "genutzte_erkenntnisse": [dict(id=c["id"], status=c["status"], aussage=c["statement"]) for c in claims
                                  if c["id"] in valid],
        "genutzte_abschnitte": [dict(id=s["id"], url=s["source_url"], pfad=s["heading_path"]) for s in sections
                                if s["id"] in valid],
    }
