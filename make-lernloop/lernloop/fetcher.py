"""Abgesicherter, nur lesender Seitenabruf.

Durchgesetzt im Code (nicht per Prompt):
- nur https, nur GET, nur freigegebene Hosts bzw. Pfadpräfixe,
- jede Weiterleitung wird erneut gegen die Freigabe geprüft,
- der Hostname wird aufgelöst und nur öffentliche IP-Adressen werden akzeptiert;
  verbunden wird genau mit der geprüften IP (Schutz vor DNS-Rebinding),
- robots.txt wird beachtet, Abrufrate und Seitengröße sind begrenzt,
- ohne bestätigte Prüfung der Nutzungsbedingungen (fetch.terms_reviewed) kein Abruf.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

from . import db as dbm


TERMS_MESSAGE = (
    "Abruf gesperrt: fetch.terms_reviewed ist false. Erst robots.txt und Nutzungsbedingungen von Make "
    "prüfen (Entscheidung E5), dann in lernloop.toml auf true setzen."
)


class FetchRefused(Exception):
    """Abruf aus Regelgründen verweigert (kein Netzwerkfehler)."""


class FetchFailed(Exception):
    """Netzwerk- oder Serverfehler."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    text: str
    bytes: int


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


class UrlPolicy:
    def __init__(self, allowed_hosts: list[str], allowed_path_prefixes: dict[str, list[str]]):
        self.hosts = {h.lower() for h in allowed_hosts}
        self.prefixes = {h.lower(): list(p) for h, p in allowed_path_prefixes.items()}

    def check(self, url: str, robots: bool = False) -> tuple[str, str]:
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise FetchRefused(f"Nur https erlaubt: {url}")
        if parts.username or parts.password:
            raise FetchRefused(f"Zugangsdaten in URL nicht erlaubt: {url}")
        if parts.port not in (None, 443):
            raise FetchRefused(f"Nur Port 443 erlaubt: {url}")
        host = (parts.hostname or "").lower()
        path = parts.path or "/"
        if host in self.hosts:
            return host, path
        if host in self.prefixes:
            if robots and path == "/robots.txt":
                return host, path
            if any(path.startswith(p) for p in self.prefixes[host]):
                return host, path
        raise FetchRefused(f"Ziel nicht freigegeben: {url}")

    def allows(self, url: str) -> bool:
        try:
            self.check(url)
            return True
        except FetchRefused:
            return False


def resolve_public(host: str) -> str:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchFailed(f"DNS-Auflösung fehlgeschlagen für {host}: {exc}") from exc
    addresses = []
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise FetchRefused(f"{host} löst auf eine nicht-öffentliche Adresse auf ({ip})")
        addresses.append(str(ip))
    if not addresses:
        raise FetchFailed(f"Keine Adresse für {host}")
    return addresses[0]


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Verbindet mit einer vorab geprüften IP, prüft das Zertifikat aber für den Hostnamen."""

    def __init__(self, host: str, ip: str, timeout: float):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self._pinned_ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._pinned_ip, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


Transport = Callable[[str, str, str, dict, float, int], tuple[int, dict, bytes]]


def https_transport(host: str, ip: str, path_and_query: str, headers: dict, timeout: float, max_bytes: int):
    conn = _PinnedHTTPSConnection(host, ip, timeout)
    try:
        conn.request("GET", path_and_query, headers=headers)
        resp = conn.getresponse()
        body = resp.read(max_bytes + 1)
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, body
    except (OSError, http.client.HTTPException) as exc:
        raise FetchFailed(f"Abruf fehlgeschlagen: {exc}") from exc
    finally:
        conn.close()


class Fetcher:
    def __init__(self, cfg_fetch: dict, conn, session_id: str | None = None,
                 transport: Transport = https_transport,
                 resolver: Callable[[str], str] = resolve_public,
                 sleep: Callable[[float], None] = time.sleep,
                 on_fetch: Callable[[], None] | None = None):
        self.cfg = cfg_fetch
        self.conn = conn
        self.session_id = session_id
        self.policy = UrlPolicy(cfg_fetch["allowed_hosts"], cfg_fetch.get("allowed_path_prefixes", {}))
        self.transport = transport
        self.resolver = resolver
        self.sleep = sleep
        self.on_fetch = on_fetch
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}

    # -- öffentliche API -------------------------------------------------
    def fetch(self, url: str, accept_types: tuple[str, ...] = ("text/html",)) -> FetchResult:
        url = normalize_url(url)
        self.policy.check(url)
        host = urlsplit(url).hostname
        if not self._robots_allowed(host, url):
            raise FetchRefused(f"robots.txt verbietet den Abruf: {url}")
        return self._get(url, accept_types)

    # -- intern ------------------------------------------------------------
    def _get(self, url: str, accept_types: tuple[str, ...], robots: bool = False) -> FetchResult:
        if not self.cfg.get("terms_reviewed"):
            raise FetchRefused(TERMS_MESSAGE)  # gilt für jeden Netzwerkzugriff, auch robots.txt
        original = url
        max_bytes = int(self.cfg["max_page_bytes"])
        for _ in range(int(self.cfg["max_redirects"]) + 1):
            host, _path = self.policy.check(url, robots=robots)
            if self.on_fetch:
                self.on_fetch()  # Limitprüfung vor jedem echten Netzwerkabruf
            self._rate_limit(host)
            ip = self.resolver(host)
            parts = urlsplit(url)
            pq = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            headers = {
                "User-Agent": self.cfg["user_agent"],
                "Accept": ", ".join(accept_types),
                "Accept-Encoding": "identity",
            }
            try:
                status, resp_headers, body = self.transport(
                    host, ip, pq, headers, float(self.cfg["timeout_seconds"]), max_bytes
                )
            except FetchFailed as exc:
                self._log(url, None, 0, str(exc))
                raise
            self._log(url, status, len(body), None)
            if status in (301, 302, 303, 307, 308):
                location = resp_headers.get("location")
                if not location:
                    raise FetchFailed(f"Weiterleitung ohne Ziel: {url}")
                url = normalize_url(urljoin(url, location))
                continue  # neues Ziel wird oben erneut gegen die Freigabe geprüft
            if len(body) > max_bytes:
                raise FetchRefused(f"Seite größer als {max_bytes} Bytes: {url}")
            ctype = resp_headers.get("content-type", "")
            mime = ctype.split(";")[0].strip().lower()
            if status == 200 and accept_types and mime not in accept_types:
                raise FetchRefused(f"Inhaltstyp {mime or '?'} nicht erlaubt: {url}")
            charset = "utf-8"
            if "charset=" in ctype:
                charset = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
            try:
                text = body.decode(charset, errors="replace")
            except LookupError:
                text = body.decode("utf-8", errors="replace")
            return FetchResult(original, url, status, mime, text, len(body))
        raise FetchRefused(f"Zu viele Weiterleitungen: {original}")

    def _rate_limit(self, host: str) -> None:
        gap = float(self.cfg["min_seconds_between_requests_per_host"])
        last = self._last_request.get(host)
        if last is not None:
            wait = gap - (time.monotonic() - last)
            if wait > 0:
                self.sleep(wait)
        self._last_request[host] = time.monotonic()

    def _robots_allowed(self, host: str, url: str) -> bool:
        parser = self._robots.get(host)
        if parser is None:
            parser = self._load_robots(host)
            self._robots[host] = parser
        return parser.can_fetch(self.cfg["user_agent"], url)

    def _load_robots(self, host: str) -> urllib.robotparser.RobotFileParser:
        parser = urllib.robotparser.RobotFileParser()
        row = self.conn.execute("SELECT status, body, fetched_at FROM robots WHERE host=?", (host,)).fetchone()
        if row is None or _older_than_days(row["fetched_at"], 7):
            try:
                res = self._get(f"https://{host}/robots.txt", ("text/plain",), robots=True)
                status, body = res.status, res.text
            except FetchRefused:
                if not self.cfg.get("terms_reviewed"):
                    raise
                status, body = 403, ""
            except FetchFailed:
                status, body = 0, ""
            self.conn.execute(
                "INSERT OR REPLACE INTO robots(host, fetched_at, status, body) VALUES(?,?,?,?)",
                (host, dbm.now(), status, body),
            )
        else:
            status, body = row["status"], row["body"]
        if status == 200:
            parser.parse(body.splitlines())
        elif status in (404, 410):
            parser.parse([])  # keine robots.txt → alles erlaubt
        else:
            parser.parse(["User-agent: *", "Disallow: /"])  # unklar → vorsichtshalber nichts
        return parser

    def robots_sitemaps(self, host: str) -> list[str]:
        parser = self._robots.get(host) or self._load_robots(host)
        self._robots[host] = parser
        return list(parser.site_maps() or [])

    def _log(self, url: str, status: int | None, size: int, error: str | None) -> None:
        self.conn.execute(
            "INSERT INTO fetch_log(session_id, url, status, bytes, error, created_at) VALUES(?,?,?,?,?,?)",
            (self.session_id, url, status, size, error, dbm.now()),
        )


def _older_than_days(iso: str, days: int) -> bool:
    from datetime import datetime, timezone

    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - then).days >= days
