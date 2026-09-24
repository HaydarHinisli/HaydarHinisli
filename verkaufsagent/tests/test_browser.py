"""End-to-End-Tests gegen einen nachgebauten Wäsche-Marktplatz.

Die Seiten werden per Playwright-Routing durch lokale HTML-Seiten ersetzt.
Geprüft wird der komplette Ablauf: Formular per Klick anlernen (Assistent),
Angebot einstellen, Preis senken, Verkauf erkennen.
"""
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import yaml
from PIL import Image

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from verkaufsagent.agent import Agent  # noqa: E402
from verkaufsagent.anlernen import Assistent  # noqa: E402
from verkaufsagent.konfiguration import BrowserEinstellungen, KiEinstellungen, Konfiguration  # noqa: E402
from verkaufsagent.modelle import Produkt  # noqa: E402
from verkaufsagent.plattformdef import Register  # noqa: E402
from verkaufsagent.plattformen import Marktplatz  # noqa: E402
from verkaufsagent.speicher import Speicher  # noqa: E402
from verkaufsagent.texte import TextGenerator  # noqa: E402

BASIS = "https://www.waesche-markt.test"

NEU = """<!doctype html><html><body>
<h1>Neues Angebot</h1>
<form action="/angebot/speichern" method="get">
 <div class="upload"><button type="button" onclick="document.getElementById('datei-input').click()">Fotos hinzufügen</button>
   <input type="file" id="datei-input" name="fotos" multiple hidden></div>
 <input id="titel" name="titel" placeholder="Titel">
 <textarea name="text"></textarea>
 <input id="preis" name="preis">
 <div class="dd" role="button" data-testid="kategorie-auswahl"
      onclick="document.getElementById('kat-liste').style.display='block'">Kategorie wählen</div>
 <ul id="kat-liste" style="display:none">
   <li onclick="kat.value=this.textContent; this.parentNode.style.display='none'">Slips</li>
   <li onclick="kat.value=this.textContent; this.parentNode.style.display='none'">BHs</li>
 </ul>
 <input type="hidden" id="kat" name="kategorie">
 <select name="groesse"><option value="">-</option><option>S</option><option>M</option><option>L</option></select>
 <input id="tragedauer" name="tragedauer" placeholder="Tragedauer">
 <button type="submit" class="los">Angebot veröffentlichen</button>
</form></body></html>"""

ANSICHT = """<!doctype html><html><body><h1>Spitzenslip</h1>{verkauft}
<p>Aufrufe: <span class="aufrufe">{aufrufe}</span></p><p>Merkliste: <span id="merkliste">{merk}</span></p>
</body></html>"""

BEARBEITEN = """<!doctype html><html><body><form action="/angebot/aktualisieren" method="get">
<input type="hidden" name="id" value="{id}"><input id="preis" name="preis" value="25">
<button type="submit" class="speichern">Änderungen speichern</button></form></body></html>"""


class Markt:
    def __init__(self):
        self.gesendet: list[dict] = []
        self.aufrufe, self.merk, self.verkauft = 3, 0, False

    def route(self, route):
        url = urlparse(route.request.url)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        html = lambda body: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)  # noqa: E731
        if url.path == "/angebot/neu":
            return html(NEU)
        if url.path == "/angebot/speichern":
            self.gesendet.append({"pfad": url.path, **q})
            # Zwischenseite mit JavaScript-Weiterleitung (wie bei vielen echten Seiten)
            return html("<p>Wird gespeichert …</p><script>setTimeout(() => location.replace('/angebot/48151-spitzenslip'), 300)</script>")
        if url.path == "/angebot/aktualisieren":
            self.gesendet.append({"pfad": url.path, **q})
            return html(f"<script>location.replace('/angebot/{q['id']}')</script>")
        if url.path.endswith("/bearbeiten"):
            return html(BEARBEITEN.format(id=url.path.split("/")[2]))
        if url.path.startswith("/angebot/"):
            return html(ANSICHT.format(aufrufe=self.aufrufe, merk=self.merk,
                                       verkauft="<b>Verkauft</b>" if self.verkauft else ""))
        return html("<html><body>Startseite</body></html>")


@pytest.fixture
def umgebung(tmp_path):
    foto = tmp_path / "foto1.jpg"
    Image.new("RGB", (400, 300), "black").save(foto)
    eigene = tmp_path / "daten" / "plattformen"
    eigene.mkdir(parents=True)
    (eigene / "testmarkt.yaml").write_text(yaml.safe_dump({
        "name": "testmarkt", "anzeigename": "Testmarkt", "basis_url": BASIS,
        "felder": {
            "fotos": {"typ": "datei", "pflicht": True}, "titel": {"typ": "text", "pflicht": True},
            "beschreibung": {"typ": "text", "pflicht": True}, "preis": {"typ": "text", "pflicht": True},
            "kategorie": {"typ": "auswahl"}, "groesse": {"typ": "auswahl"},
        },
    }, sort_keys=False), encoding="utf-8")
    konf = Konfiguration(auto_veroeffentlichen=True, pause_zwischen_inseraten_s=10, datenordner=tmp_path / "daten",
                         ki=KiEinstellungen(aktiv=False), browser=BrowserEinstellungen(langsam_ms=0, timeout_ms=6000))
    produkt = Produkt.model_validate(dict(
        id="slip-001", name="Spitzenslip", marke="Hunkemöller", preis=25, groesse="M", farbe="Schwarz",
        notizen="Nichtraucherhaushalt.", fotos=[foto], plattformen=["testmarkt"],
        testmarkt={"kategorie": ["Slips"], "felder": {"tragedauer": "1 Tag"}},
    ))
    markt = Markt()
    register = Register(konf.datenordner)
    with sync_playwright() as pw:
        def fabrik(name):
            m = Marktplatz(pw, konf, register.lade(name))
            m.ctx.route("**/*", markt.route)
            return m
        yield konf, register, produkt, markt, fabrik


def anlernen(fabrik, register, erst_startseite=False):
    """Spielt den Nutzer im Assistenten: jede Frage = eine Aktion im Browser."""
    m = fabrik("testmarkt")
    p = m.page

    def klick(sel):
        return lambda: p.click(sel)

    def gehe(pfad):
        return lambda: p.goto(BASIS + pfad)

    start = ["", gehe("/angebot/neu")] if erst_startseite else [gehe("/angebot/neu")]
    schritte = [
        *start,                                             # 1) Formular öffnen
        klick("text=Fotos hinzufügen"),                     # Fotos
        klick("#titel"), klick("textarea"), klick("#preis"),
        klick("[data-testid=kategorie-auswahl]"),           # eigenes Dropdown
        klick("select[name=groesse]"),
        "tragedauer", "t", "j", klick("#tragedauer"),       # 3) Zusatzfeld
        "",                                                 # keine weiteren Felder
        klick("button.los"),                                # 4) Absenden (darf NICHT auslösen)
        gehe("/angebot/48151-spitzenslip"),                 # 5) Angebotsansicht
        klick(".aufrufe"), klick("#merkliste"), "Verkauft",
        gehe("/angebot/48151/bearbeiten"),                  # 6) Bearbeiten-Seite
        klick("button.speichern"),
    ]

    def frage(_text):
        schritt = schritte.pop(0)
        return schritt if isinstance(schritt, str) else (schritt() and "") or ""

    try:
        d = Assistent(m, register, frage=frage, ausgabe=lambda *a: None).ausfuehren()
        assert not schritte, "nicht alle Schritte abgefragt"
        return d
    finally:
        m.schliessen()


def test_anlernen_und_kompletter_ablauf(umgebung, monkeypatch):
    konf, register, produkt, markt, fabrik = umgebung
    d = anlernen(fabrik, register)

    # Assistent hat alles angelernt – und beim Anlernen nichts abgeschickt
    assert markt.gesendet == []
    assert d.eingerichtet, d.fehlend()
    assert d.neu_url == f"{BASIS}/angebot/neu"
    assert d.felder["fotos"].selektor[0] == "#datei-input"
    assert d.felder["titel"].selektor[0] == "#titel"
    assert d.felder["kategorie"].selektor[0] == 'div[data-testid="kategorie-auswahl"]'
    assert d.felder["tragedauer"].pflicht
    assert d.anzeige_url == f"{BASIS}/angebot/{{id}}" and d.bearbeiten_url == f"{BASIS}/angebot/{{id}}/bearbeiten"
    assert d.verkauft_texte == ["Verkauft"] and d.aufrufe and d.favoriten
    assert register.lade("testmarkt").eingerichtet  # gespeichert

    monkeypatch.setattr("verkaufsagent.agent.time.sleep", lambda s: None)
    zeit = [datetime(2026, 9, 1, 10, 0)]
    speicher = Speicher(konf.datenordner)
    agent = Agent(konf, [produkt], speicher, TextGenerator(konf.ki, register.lade), fabrik, jetzt=lambda: zeit[0])
    try:
        assert agent.inseriere_neue() == 1
        g = markt.gesendet[0]
        assert g["titel"].startswith("Hunkemöller Spitzenslip")
        assert "Tragedauer: 1 Tag" in g["text"] and "diskret" in g["text"]
        assert (g["preis"], g["kategorie"], g["groesse"], g["tragedauer"], g["fotos"]) == ("25", "Slips", "M", "1 Tag", "foto1.jpg")
        i = speicher.hole("slip-001", "testmarkt")
        assert (i.status, i.anzeige_id, i.url, i.preis_aktuell) == ("online", "48151", f"{BASIS}/angebot/48151", 25)
        assert agent.inseriere_neue() == 0  # nie doppelt

        zeit[0] += timedelta(days=3)  # zu früh
        agent.pflege_inserate()
        assert speicher.hole("slip-001", "testmarkt").preis_aktuell == 25

        zeit[0] += timedelta(days=12)  # 15 Tage, kaum Aufrufe, keine Merker -> -5 %
        agent.pflege_inserate()
        i = speicher.hole("slip-001", "testmarkt")
        assert (i.preis_aktuell, i.aufrufe, i.favoriten) == (23, 3, 0)
        assert markt.gesendet[-1] == {"pfad": "/angebot/aktualisieren", "id": "48151", "preis": "23"}

        markt.merk = 7  # viele Merker -> keine weitere Senkung
        zeit[0] += timedelta(days=30)
        agent.pflege_inserate()
        assert speicher.hole("slip-001", "testmarkt").preis_aktuell == 23

        markt.verkauft = True  # Verkauf wird erkannt
        agent.pflege_inserate()
        assert speicher.hole("slip-001", "testmarkt").status == "entfernt"
    finally:
        agent.schliessen()


def test_startseite_wird_nicht_als_formular_gespeichert(umgebung):
    konf, register, produkt, markt, fabrik = umgebung
    d = anlernen(fabrik, register, erst_startseite=True)  # Enter auf der Startseite -> Warnung, dann Formular
    assert d.neu_url == f"{BASIS}/angebot/neu" and d.eingerichtet


def test_nicht_eingerichtete_plattform_wird_klar_gemeldet(umgebung):
    konf, register, produkt, markt, fabrik = umgebung
    speicher = Speicher(konf.datenordner)
    agent = Agent(konf, [produkt], speicher, TextGenerator(konf.ki, register.lade), fabrik)
    try:
        assert agent.inseriere_neue() == 0
        assert markt.gesendet == []
    finally:
        agent.schliessen()


def test_mitgelieferte_vorlagen():
    register = Register(__import__("pathlib").Path("/nicht/vorhanden"))
    assert {"crazyslip", "creamsi", "panty"} <= set(register.namen())
    for name in ("crazyslip", "creamsi", "panty"):
        d = register.lade(name)
        assert not d.eingerichtet and "neu_url" in d.fehlend()
        assert d.felder["fotos"].typ == "datei" and d.stil


PANTY_FORM = """<!doctype html><html><body>
<input id="title"><select id="price"><option value="">Select price</option>
<option value="p10">10</option><option value="p15">15</option><option value="p20">20</option><option value="p25">25</option></select>
<select id="currency"><option value="usd">$ USD</option><option value="eur">€ EUR</option></select>
<select id="size"><option value="">-</option><option>Small</option><option>Medium</option><option>Large</option></select>
</body></html>"""


def test_menues_wie_bei_panty(umgebung):
    konf, register, produkt, markt, fabrik = umgebung
    m = fabrik("testmarkt")
    try:
        m.page.set_content(PANTY_FORM)
        preis = m.page.locator("#price")
        assert m.preis_setzen(preis, 25, 17.5) == 25 and preis.input_value() == "p25"
        assert m.preis_setzen(preis, 23, 17.5) == 20 and preis.input_value() == "p20"   # nächste Stufe darunter
        with pytest.raises(Exception):
            m.preis_setzen(preis, 24, 21)                                             # keine Stufe erlaubt
        m._option_waehlen(m.page.locator("#currency"), "EUR")
        assert m.page.locator("#currency").input_value() == "eur"
        m._option_waehlen(m.page.locator("#size"), "M")                                # 'M' -> 'Medium'
        assert m.page.locator("#size").input_value() == "Medium"
        m.page.locator("#title").fill("x")
        assert m.preis_setzen(m.page.locator("#title"), 22.5, 0) == 22.5              # Textfeld: freier Preis
        assert m.page.locator("#title").input_value() == "22,50"
    finally:
        m.schliessen()


SPA_BASIS = "https://www.spa-markt.test"
SPA_SEITE = """<!doctype html><html><body>
<nav><a href="#" id="logo" onclick="zeige('start');return false">panty</a>
<a href="#" id="nav-offers" onclick="zeige('angebote');return false">MY OFFERS</a></nav>
<div id="start">Willkommen</div>
<div id="angebote" hidden><button type="button" onclick="zeige('kategorien')">+ POST OFFER</button></div>
<div id="kategorien" hidden><ul><li onclick="zeige('formular')">Used Panties</li><li>Foot fetish</li></ul></div>
<form id="formular" hidden action="/offer/save" method="get">
  <input name="title" id="title"><select name="price" id="price"><option value="">Select price</option>
  <option>15</option><option>20</option><option>25</option></select>
  <textarea name="desc" id="desc"></textarea><input type="file" name="bild" id="bild">
  <button type="submit" id="post">Post offer</button>
</form>
<script>function zeige(id){for(const b of ['start','angebote','kategorien','formular'])document.getElementById(b).hidden=(b!==id);}</script>
</body></html>"""


def test_formular_ohne_eigene_adresse_wie_panty(tmp_path, monkeypatch):
    """Formular erscheint nur per Klicks (Adresse bleibt '/'): Klickweg wird angelernt und beim Einstellen nachgeklickt."""
    foto = tmp_path / "f.jpg"
    Image.new("RGB", (50, 50)).save(foto)
    eigene = tmp_path / "daten" / "plattformen"
    eigene.mkdir(parents=True)
    (eigene / "spa.yaml").write_text(yaml.safe_dump({
        "name": "spa", "anzeigename": "SPA", "basis_url": SPA_BASIS, "sprache": "en",
        "felder": {"titel": {"typ": "text", "pflicht": True}, "preis": {"typ": "auswahl", "pflicht": True},
                   "beschreibung": {"typ": "text", "pflicht": True}, "fotos": {"typ": "datei", "pflicht": True}},
    }, sort_keys=False), encoding="utf-8")
    konf = Konfiguration(auto_veroeffentlichen=True, datenordner=tmp_path / "daten",
                         ki=KiEinstellungen(aktiv=False), browser=BrowserEinstellungen(langsam_ms=0, timeout_ms=6000))
    register = Register(konf.datenordner)
    gesendet = []

    def route(r):
        url = urlparse(r.request.url)
        if url.path == "/offer/save":
            gesendet.append({k: v[0] for k, v in parse_qs(url.query).items()})
            return r.fulfill(status=200, content_type="text/html", body="<script>location.replace('/offer/77712')</script>")
        if url.path.startswith("/offer/"):
            return r.fulfill(status=200, content_type="text/html; charset=utf-8", body=SPA_SEITE)  # mit Kopfbereich/Logo
        return r.fulfill(status=200, content_type="text/html; charset=utf-8", body=SPA_SEITE)

    with sync_playwright() as pw:
        def fabrik(name):
            m = Marktplatz(pw, konf, register.lade(name))
            m.ctx.route("**/*", route)
            return m

        m = fabrik("spa")
        p = m.page
        klick = lambda sel: (lambda: p.click(sel))  # noqa: E731
        schritte = [
            klick("#nav-offers"), klick("text=+ POST OFFER"), klick("text=Used Panties"),  # Formular öffnen (Adresse bleibt /)
            "j",                                                                           # "Formular ist wirklich hier"
            klick("#logo"), klick("#nav-offers"), klick("text=+ POST OFFER"), (klick("text=Used Panties"), "f"),  # Klickweg
            klick("#title"), klick("#price"), klick("#desc"), klick("#bild"),              # Felder
            "",                                                                            # keine weiteren Felder
            klick("#post"),                                                                # Absenden (nicht ausgelöst)
            "", "",                                                                        # optionale Seiten überspringen
        ]

        def frage(_text):
            s = schritte.pop(0)
            if isinstance(s, tuple):
                s[0]()
                return s[1]
            return s if isinstance(s, str) else (s() and "") or ""

        # Schritt 1: der Nutzer klickt sich erst durch, dann Enter -> Warnung "nur Startseite" -> 'j'
        erst = [schritte.pop(0), schritte.pop(0), schritte.pop(0)]
        schritte.insert(0, lambda: [f() for f in erst])
        try:
            d = Assistent(m, register, frage=frage, ausgabe=lambda *a: None).ausfuehren()
        finally:
            m.schliessen()
        assert not schritte
        assert len(d.navigation) == 4 and d.eingerichtet, d.fehlend()
        assert any("MY OFFERS" in s for s in d.navigation[1])
        assert gesendet == []

        produkt = Produkt.model_validate(dict(id="s1", name="Orange lace G-string", preis=24, groesse="M",
                                              fotos=[foto], plattformen=["spa"]))
        zweites = Produkt.model_validate(dict(id="s2", name="Red lace thong", preis=15, fotos=[foto], plattformen=["spa"]))
        speicher = Speicher(konf.datenordner)
        agent = Agent(konf, [produkt, zweites], speicher, TextGenerator(konf.ki, register.lade), fabrik)
        seitenaufrufe = []
        monkeypatch.setattr("verkaufsagent.agent.time.sleep", lambda s: None)
        try:
            original = Marktplatz.veroeffentliche

            def zaehlen(self, *a, **k):
                self.page.on("framenavigated", lambda f: f == self.page.main_frame and seitenaufrufe.append(f.url))
                return original(self, *a, **k)
            monkeypatch.setattr(Marktplatz, "veroeffentliche", zaehlen)
            assert agent.inseriere_neue() == 2
        finally:
            agent.schliessen()
        # Startseite nur einmal geladen – das zweite Angebot kam per Klick (Logo …) zum Formular
        assert sum(1 for u in seitenaufrufe if urlparse(u).path == "/") <= 2
        assert gesendet[1]["title"].startswith("Red lace thong") and gesendet[1]["price"] == "15"
        assert gesendet[0]["title"].startswith("Orange lace G-string") and gesendet[0]["price"] == "20"  # Stufe <= 24
        assert "Size: M" in gesendet[0]["desc"]
        i = speicher.hole("s1", "spa")
        assert (i.status, i.anzeige_id, i.preis_aktuell) == ("online", "77712", 20)


LOGIN_SEITE = """<!doctype html><html><body>
<header><a href="#" id="logo">site</a>
<a href="#" id="login-link" onclick="document.getElementById('login').hidden=false;return false">LOGIN</a>
<a href="#" id="offers">MY OFFERS</a></header>
<form id="login" hidden onsubmit="event.preventDefault();
  if (email.value==='ich@test.de' && pw.value==='geheim') {
    document.cookie = merken.checked ? 'sess=1; path=/; max-age=86400' : 'sess=1; path=/'; location.reload(); }">
  <input id="email"><input id="pw" type="password">
  <label><input type="checkbox" id="merken"> Remember me</label><button id="login-btn">Sign in</button>
</form>
<script>
  const drin = document.cookie.includes('sess=1');
  document.getElementById('login-link').hidden = drin;
  document.getElementById('offers').hidden = !drin;
</script></body></html>"""


def test_login_anlernen_cookies_sichern_und_automatisch_anmelden(tmp_path):
    eigene = tmp_path / "daten" / "plattformen"
    eigene.mkdir(parents=True)
    (eigene / "lg.yaml").write_text(yaml.safe_dump({"name": "lg", "anzeigename": "LG", "basis_url": "https://www.lg.test"}),
                                    encoding="utf-8")
    konf = Konfiguration(datenordner=tmp_path / "daten", browser=BrowserEinstellungen(langsam_ms=0, timeout_ms=5000))
    register = Register(konf.datenordner)
    route = lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=LOGIN_SEITE)  # noqa: E731

    with sync_playwright() as pw:
        def oeffnen():
            m = Marktplatz(pw, konf, register.lade("lg"))
            m.ctx.route("**/*", route)
            return m

        # 1) Login anlernen (Nutzer ist abgemeldet, klickt LOGIN, dann die Felder)
        m = oeffnen()
        p = m.page
        schritte = ["", (lambda: p.click("#login-link"), "f"),
                    lambda: p.click("#email"), lambda: p.click("#pw"), lambda: p.click("#merken"),
                    lambda: p.click("#login-btn"), "ich@test.de"]

        def frage(_t):
            s = schritte.pop(0)
            if isinstance(s, tuple):
                s[0]()
                return s[1]
            return s if isinstance(s, str) else (s() and "") or ""
        try:
            d = Assistent(m, register, frage=frage, ausgabe=lambda *a: None).login_anlernen(passwort_frage=lambda _t: "geheim")
            assert d.login_eingerichtet and d.abgemeldet_zeichen and not schritte
            assert not m._abgemeldet()                      # Test-Anmeldung am Ende hat geklappt
            assert d.login_merken
            dauerhaft = [c for c in m.ctx.cookies() if c["name"] == "sess"]
            assert dauerhaft and dauerhaft[0]["expires"] > 0   # „Remember me“ wurde angehakt
        finally:
            m.schliessen()                                  # sichert auch das Sitzungs-Cookie
        assert (tmp_path / "daten" / "browser" / "lg-cookies.json").exists()

        # 2) Neuer Browser: Sitzungs-Cookie wird wiederhergestellt -> weiterhin angemeldet
        m = oeffnen()
        try:
            m.page.goto("https://www.lg.test/")
            assert not m._abgemeldet()
        finally:
            m.ctx.clear_cookies()
            m.ctx.close()                                   # ohne Sichern schließen
        (tmp_path / "daten" / "browser" / "lg-cookies.json").unlink()

        # 3) Ohne Cookies: der Agent meldet sich selbst an
        m = oeffnen()
        try:
            m.page.goto("https://www.lg.test/")
            assert m._abgemeldet()
            m.sicherstellen_angemeldet()
            assert not m._abgemeldet()
        finally:
            m.schliessen()


def test_passwort_wird_nie_angezeigt_und_felder_nicht_als_klickweg_gemerkt(tmp_path):
    eigene = tmp_path / "daten" / "plattformen"
    eigene.mkdir(parents=True)
    (eigene / "lg.yaml").write_text(yaml.safe_dump({"name": "lg", "anzeigename": "LG", "basis_url": "https://www.lg.test"}),
                                    encoding="utf-8")
    konf = Konfiguration(datenordner=tmp_path / "daten", browser=BrowserEinstellungen(langsam_ms=0, timeout_ms=5000))
    register = Register(konf.datenordner)
    ausgaben = []
    with sync_playwright() as pw:
        m = Marktplatz(pw, konf, register.lade("lg"))
        m.ctx.route("**/*", lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=LOGIN_SEITE))
        p = m.page

        def tippen_und_klicken():
            p.evaluate("document.getElementById('login').hidden = false")
            p.fill("#pw", "SuperGeheim123!")
            p.click("#pw")

        schritte = [tippen_und_klicken, (lambda: p.click("#login-link"), "f")]

        def frage(_t):
            s = schritte.pop(0)
            if isinstance(s, tuple):
                s[0]()
                return s[1]
            return (s() and "") or ""
        try:
            m.page.goto("https://www.lg.test/")
            a = Assistent(m, register, frage=frage, ausgabe=lambda *x: ausgaben.append(" ".join(map(str, x))))
            weg = a._klickweg("das Login-Formular")
        finally:
            m.schliessen()
    alles = "\n".join(ausgaben)
    assert "SuperGeheim123!" not in alles and "Passwort-Feld" in alles
    assert len(weg) == 1 and any("login-link" in s or "LOGIN" in s for s in weg[0])


GESTALTETE_MENUES = """<!doctype html><html><body><form id="cform"><div class="zeile">
 <div><div class="wrap"><input class="dd" readonly value="Select price">
   <select name="price" style="display:none"><option value="">Select price</option><option value="10">$ 10</option>
   <option value="20">$ 20</option><option value="25">$ 25</option></select></div></div>
 <div><div class="wrap"><input class="dd" readonly value="$ USD">
   <select name="currency" style="opacity:0;position:absolute"><option value="USD">$ USD</option><option value="EUR">€ EUR</option></select></div></div>
 <div><div class="wrap"><input class="dd" readonly value="Select size">
   <select name="size" style="display:none"><option value="">Select size</option><option value="S">Small</option>
   <option value="M">Medium</option></select></div></div>
</div></form></body></html>"""


def test_gestaltete_menues_mit_verstecktem_select_wie_panty(umgebung):
    konf, register, produkt, markt, fabrik = umgebung
    m = fabrik("testmarkt")
    try:
        m.page.set_content(GESTALTETE_MENUES)
        feld = lambda n: m.page.locator(f"#cform > div:nth-of-type(1) > div:nth-of-type({n}) > div > input")  # noqa: E731
        assert m.preis_setzen(feld(1), 24, 17.5) == 20
        assert m.page.locator("select[name=price]").input_value() == "20" and feld(1).input_value() == "$ 20"
        from verkaufsagent.plattformdef import Feld
        m._fuellen("waehrung", Feld(typ="auswahl", selektor=["#cform > div:nth-of-type(1) > div:nth-of-type(2) > div > input"]), "EUR")
        m._fuellen("groesse", Feld(typ="auswahl", selektor=["#cform > div:nth-of-type(1) > div:nth-of-type(3) > div > input"]), "M")
        assert m.page.locator("select[name=currency]").input_value() == "EUR"      # nicht das Preis-Menü!
        assert m.page.locator("select[name=size]").input_value() == "M" and feld(3).input_value() == "Medium"
        assert m.page.locator("select[name=price]").input_value() == "20"          # unverändert
    finally:
        m.schliessen()


KLICKLISTE = """<!doctype html><html><body>
<input id="preis" readonly value="Select price" onclick="liste.hidden=false">
<ul id="liste" hidden><li onclick="preis.value=this.textContent;liste.hidden=true">$ 15</li>
<li onclick="preis.value=this.textContent;liste.hidden=true">$ 20</li>
<li onclick="preis.value=this.textContent;liste.hidden=true">$ 30</li></ul></body></html>"""


def test_preis_aus_reiner_klickliste(umgebung):
    konf, register, produkt, markt, fabrik = umgebung
    m = fabrik("testmarkt")
    try:
        m.page.set_content(KLICKLISTE)
        assert m.preis_setzen(m.page.locator("#preis"), 25, 17.5) == 20
        assert m.page.locator("#preis").input_value() == "$ 20"
    finally:
        m.schliessen()


def test_link_im_zugeklappten_menue_wird_ausgeloest(umgebung):
    konf, register, produkt, markt, fabrik = umgebung
    m = fabrik("testmarkt")
    try:
        m.page.set_content("""<ul id="dd-acc" style="display:none"><li><a href="#" id="off"
            onclick="document.body.dataset.ok='1';return false">My Offers</a></li></ul>""")
        m._klick_schritt(['a:has-text("My Offers")', "#dd-acc > li:nth-of-type(1) > a"], "My Offers", 1000)
        assert m.page.evaluate("document.body.dataset.ok") == "1"
        with pytest.raises(Exception, match="angemeldet"):
            m._klick_schritt(["#gibt-es-nicht"], "X", 500)
    finally:
        m.schliessen()
