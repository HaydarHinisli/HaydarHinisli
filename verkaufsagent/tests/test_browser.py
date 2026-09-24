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


def anlernen(fabrik, register):
    """Spielt den Nutzer im Assistenten: jede Frage = eine Aktion im Browser."""
    m = fabrik("testmarkt")
    p = m.page

    def klick(sel):
        return lambda: p.click(sel)

    def gehe(pfad):
        return lambda: p.goto(BASIS + pfad)

    schritte = [
        gehe("/angebot/neu"),                               # 1) Formular öffnen
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
