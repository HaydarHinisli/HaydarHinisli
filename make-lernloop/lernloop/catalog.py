"""Seitenkatalog: welche freigegebenen Doku-Seiten gibt es?

Quellen: Sitemaps der freigegebenen Hosts (aus robots.txt bzw. /sitemap.xml) und Links aus
bereits abgerufenen Seiten. Gesucht wird lokal (FTS5) über Titel und URL-Wörter – eine
externe Suchmaschine wird nicht verwendet.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

from . import db as dbm
from .fetcher import Fetcher, FetchFailed, FetchRefused, normalize_url

_LOC = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.S | re.I)
_URL_BLOCK = re.compile(r"<url>(.*?)</url>", re.S | re.I)
_LASTMOD = re.compile(r"<lastmod>\s*(.*?)\s*</lastmod>", re.S | re.I)
_SITEMAP_TYPES = ("application/xml", "text/xml")


def url_words(url: str) -> str:
    path = urlsplit(url).path
    return " ".join(w for w in re.split(r"[/\-_.]+", path) if w and not w.isdigit())


def add_page(conn, url: str, title: str | None, via: str, lastmod: str | None = None) -> bool:
    url = normalize_url(url)
    host = urlsplit(url).hostname or ""
    exists = conn.execute("SELECT title FROM page_index WHERE url=?", (url,)).fetchone()
    if exists:
        if title and not exists["title"]:
            conn.execute("UPDATE page_index SET title=? WHERE url=?", (title, url))
            conn.execute("UPDATE page_index_fts SET title=? WHERE url=?", (title, url))
        return False
    conn.execute(
        "INSERT INTO page_index(url, host, title, lastmod, discovered_via, discovered_at) VALUES(?,?,?,?,?,?)",
        (url, host, title, lastmod, via, dbm.now()),
    )
    conn.execute("INSERT INTO page_index_fts(url, title, words) VALUES(?,?,?)", (url, title or "", url_words(url)))
    return True


def refresh_from_sitemaps(conn, fetcher: Fetcher, max_sitemaps: int = 30, log=print) -> int:
    added = 0
    queue: list[str] = []
    for host in sorted(fetcher.policy.hosts):
        found = fetcher.robots_sitemaps(host)
        queue.extend(found or [f"https://{host}/sitemap.xml"])
    seen: set[str] = set()
    while queue and len(seen) < max_sitemaps:
        sm = normalize_url(queue.pop(0))
        if sm in seen:
            continue
        seen.add(sm)
        if sm.endswith(".gz"):
            log(f"  übersprungen (komprimiert): {sm}")
            continue
        try:
            res = fetcher.fetch(sm, accept_types=_SITEMAP_TYPES)
        except (FetchRefused, FetchFailed) as exc:
            log(f"  Sitemap nicht abrufbar: {sm} ({exc})")
            continue
        if res.status != 200:
            log(f"  Sitemap {sm}: HTTP {res.status}")
            continue
        body = res.text
        if "<sitemapindex" in body[:2000].lower():
            queue.extend(html.unescape(u) for u in _LOC.findall(body))
            continue
        n = 0
        for block in _URL_BLOCK.findall(body):
            locs = _LOC.findall(block)
            if not locs:
                continue
            url = html.unescape(locs[0])
            if not fetcher.policy.allows(url):
                continue
            lm = _LASTMOD.findall(block)
            if add_page(conn, url, None, f"sitemap:{sm}", lm[0] if lm else None):
                n += 1
        added += n
        log(f"  {sm}: {n} neue Seiten")
    return added


def add_links(conn, links: list[tuple[str, str]], policy, via: str) -> int:
    n = 0
    for url, text in links:
        url = url.split("#")[0]
        if policy.allows(url) and add_page(conn, url, text or None, via):
            n += 1
    return n


def search(conn, terms: list[str], limit: int = 15, exclude: set[str] | None = None,
           prefer_hosts: list[str] | None = None) -> list[dict]:
    """Treffer nach Relevanz; Seiten bevorzugter Hosts kommen zuerst (Reihenfolge innerhalb bleibt)."""
    q = dbm.fts_query(" ".join(terms))
    if not q:
        return []
    rows = conn.execute(
        "SELECT p.url, p.host, p.title, p.lastmod FROM page_index_fts f JOIN page_index p ON p.url=f.url "
        "WHERE page_index_fts MATCH ? ORDER BY bm25(page_index_fts, 0.0, 3.0, 2.0) LIMIT ?",
        (q, limit * 4 + len(exclude or ())),
    ).fetchall()
    out = [dict(r) for r in rows if not exclude or r["url"] not in exclude]
    if prefer_hosts:
        out.sort(key=lambda r: r["host"] not in prefer_hosts)
    return [{k: r[k] for k in ("url", "title", "lastmod")} for r in out[:limit]]


def count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM page_index").fetchone()[0]
