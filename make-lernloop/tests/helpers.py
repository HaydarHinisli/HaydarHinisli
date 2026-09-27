"""Testumgebung: temporäres Projektverzeichnis, simuliertes Netz, simuliertes Modell."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from lernloop import db as dbm
from lernloop.cli import seed_topics
from lernloop.config import load_config
from lernloop.fetcher import Fetcher

FIX = Path(__file__).parent / "fixtures"

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://help.make.com/iterator</loc><lastmod>2026-05-01</lastmod></url>
<url><loc>https://help.make.com/array-aggregator</loc></url>
<url><loc>https://help.make.com/webhooks</loc></url>
<url><loc>https://evil.example.com/iterator</loc></url>
</urlset>"""


class FakeWeb:
    def __init__(self):
        self.pages = {
            "/robots.txt": (200, "text/plain", "User-agent: *\nAllow: /\nSitemap: https://help.make.com/sitemap.xml\n"),
            "/sitemap.xml": (200, "application/xml", SITEMAP),
            "/iterator": (200, "text/html; charset=utf-8", (FIX / "iterator.html").read_text()),
            "/array-aggregator": (200, "text/html", (FIX / "aggregator.html").read_text()),
            "/webhooks": (404, "text/html", "not found"),
        }
        self.redirects: dict[str, str] = {}
        self.requests: list[tuple[str, str, str]] = []

    def transport(self, host, ip, pq, headers, timeout, max_bytes):
        self.requests.append((host, ip, pq))
        if pq in self.redirects:
            return 302, {"location": self.redirects[pq]}, b""
        status, ctype, body = self.pages.get(pq, (404, "text/html", "nope"))
        return status, {"content-type": ctype}, body.encode()


def resolver_public(host):
    return "93.184.216.34"


def make_env(extra_toml: str = ""):
    tmp = Path(tempfile.mkdtemp(prefix="lernloop-test-"))
    (tmp / "lernloop.toml").write_text(f"""
[paths]
data_dir = "./data"
[fetch]
terms_reviewed = true
min_seconds_between_requests_per_host = 0
[model]
backend = "fake"
{extra_toml}
""")
    cfg = load_config(tmp / "lernloop.toml")
    cfg.data_dir.mkdir(parents=True)
    conn = dbm.connect(cfg.db_path)
    dbm.init_schema(conn)
    seed_topics(conn)
    return cfg, conn, tmp


def fetcher_factory(cfg, web: FakeWeb):
    def make(conn, sid, on_fetch):
        return Fetcher(cfg.section("fetch"), conn, sid, transport=web.transport, resolver=resolver_public,
                       sleep=lambda s: None, on_fetch=on_fetch)
    return make


def section_ids_with(prompt: str, phrase: str) -> str:
    for m in re.finditer(r'<abschnitt id="(ABS-\d+)"[^>]*>\n(.*?)\n</abschnitt>', prompt, re.S):
        if phrase in m.group(2):
            return m.group(1)
    raise AssertionError(f"Abschnitt mit {phrase!r} nicht im Prompt")


def good_responder(step, prompt, schema):
    if step == "plan":
        return {"bereits_beantwortet": False, "frage": "Was gibt der Iterator aus?",
                "begruendung": "Noch nichts bekannt", "suchbegriffe_en": ["iterator", "bundle"]}
    if step == "auswahl":
        urls = re.findall(r"- (https://\S+)", prompt)
        return {"urls": [u for u in urls if "iterator" in u] + ["https://help.make.com/erfunden"],
                "begruendung": "passt"}
    if step == "extraktion":
        if "Iterator (Testseite)" not in prompt:
            return {"aussagen": [], "offene_punkte": []}
        sid = section_ids_with(prompt, "output as a separate bundle")
        return {"aussagen": [
            {"aussage": "Der Iterator gibt jedes Array-Element als eigenes Bundle aus.",
             "zitat": "Each item of the array is output as a separate bundle.", "abschnitt_id": sid,
             "ableitung": "direkt_zitiert", "geltungsbereich": "Iterator-Modul", "modul": "Iterator",
             "schlagworte_en": "iterator bundle array"},
            {"aussage": "Der Iterator sortiert die Elemente alphabetisch.",
             "zitat": "The Iterator sorts all items alphabetically.", "abschnitt_id": sid,
             "ableitung": "direkt_zitiert", "geltungsbereich": "Iterator-Modul", "schlagworte_en": "iterator sort"},
            {"aussage": "Nach dem Iterator laufen Folgemodule pro Bundle, daher steigt der Verbrauch.",
             "zitat": "Modules placed after the Iterator are executed once for each bundle.", "abschnitt_id": sid,
             "ableitung": "ki_schlussfolgerung", "geltungsbereich": "Iterator-Modul", "schlagworte_en": "operations"},
        ], "offene_punkte": ["Verhalten bei leerem Array"]}
    if step == "abgleich":
        return {"befunde": []}
    if step == "beurteilung":
        return {"ergebnis": "beantwortet", "begruendung": "Belegt", "fehlende_information": [],
                "fehlerklasse": "keine", "naechste_suchbegriffe_en": []}
    if step == "übung":
        ids = re.findall(r'erkenntnis id="(ERK-\d+)"', prompt)
        return {"antwort": "Drei Bundles", "genutzte_erkenntnisse": ids[:1], "offen": False}
    if step == "frage_suchbegriffe":
        return {"suchbegriffe_en": ["iterator", "bundle"]}
    if step == "antwort":
        ids = re.findall(r'id="((?:ERK|ABS)-\d+)"', prompt)
        return {"antwort": "Jedes Element wird ein Bundle.", "belege": ids[:2] + ["ERK-999999"],
                "unbelegte_teile": [], "offen": False}
    raise AssertionError(step)
