"""End-to-End-Tests der Browser-Automatisierung gegen nachgebaute Plattform-Formulare.

Die echten Webseiten werden per Playwright-Routing durch lokale HTML-Seiten
ersetzt, die dieselben Feld-IDs verwenden. So wird der komplette Ablauf
(Formular füllen, Kategorie wählen, Fotos, Absenden, ID auslesen,
Preis ändern, Statistik lesen) ohne echtes Konto geprüft.
"""
import json
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from verkaufsagent.agent import Agent  # noqa: E402
from verkaufsagent.konfiguration import BrowserEinstellungen, KiEinstellungen, Konfiguration  # noqa: E402
from verkaufsagent.modelle import Plattform, Produkt  # noqa: E402
from verkaufsagent.plattformen import KLASSEN  # noqa: E402
from verkaufsagent.speicher import Speicher  # noqa: E402
from verkaufsagent.texte import TextGenerator  # noqa: E402

KA_FORM = """<!doctype html><html><body>
<div id="gdpr"><button id="gdpr-banner-accept" onclick="document.getElementById('gdpr').remove()">Alle akzeptieren</button></div>
<form action="/p-anzeige-aufgeben-bestaetigung.html" method="get">
 <label for="postad-title">Titel</label><input id="postad-title" name="title">
 <span id="postad-category-path"></span><input type="hidden" id="cat" name="cat">
 <a id="pstad-lnk-chngeCtgry" href="#" onclick="document.getElementById('cats').style.display='block';return false">Ändern</a>
 <div id="cats" style="display:none">
  <span onclick="window.p=(window.p||[]).concat(this.textContent)">Mode &amp; Beauty</span>
  <span onclick="window.p=(window.p||[]).concat(this.textContent)">Herrenbekleidung</span>
  <button type="button" id="postad-step1-sbmt" onclick="document.getElementById('postad-category-path').textContent=window.p.join(' > ');document.getElementById('cat').value=window.p.join('>');document.getElementById('cats').style.display='none'">Weiter</button>
 </div>
 <textarea id="pstad-descrptn" name="desc"></textarea>
 <input id="pstad-price" name="price">
 <select id="priceType" name="priceType"><option value="FIXED">Festpreis</option><option value="NEGOTIABLE">VB</option></select>
 <select name="attributeMap[kleidung.condition_s]" id="condition"><option value="">-</option><option value="like_new">Sehr Gut</option><option value="good">Gut</option></select>
 <input type="radio" id="ad-shipping-enabled-true" name="ship" value="ja"><input type="radio" id="ad-shipping-enabled-false" name="ship" value="nein">
 <div id="plupld"><input type="file" name="fotos" multiple accept="image/*"></div>
 <input id="pstad-zip" name="zip"><input id="postad-contactname" name="name">
 <input type="hidden" name="adId" value="4711">
 <button id="pstad-submit" type="submit">Anzeige aufgeben</button>
</form></body></html>"""

KA_EDIT = """<!doctype html><form action="/m-meine-anzeigen.html" method="get">
<input id="pstad-price" name="price" value="45"><button id="pstad-submit" type="submit">Speichern</button></form>"""

VINTED_FORM = """<!doctype html><html><body>
<form action="/items/987654" method="get">
<input type="file" name="fotos" multiple accept="image/*">
<input data-testid="title--input" name="title"><textarea data-testid="description--input" name="desc"></textarea>
<script>
function dd(name, optionen){
  const w=document.createElement('div');
  w.innerHTML='<input data-testid="'+name+'-select-dropdown-input" readonly name="'+name+'"><input type="hidden" name="'+name+'_pfad">';
  const inp=w.children[0], pfad=w.children[1];
  inp.onclick=()=>{ const c=document.createElement('div'); c.setAttribute('data-testid',name+'-select-dropdown-content');
    let ebene=optionen;
    const zeige=()=>{ c.innerHTML=''; Object.keys(ebene).forEach(k=>{ const r=document.createElement('div'); r.textContent=k;
      r.onclick=()=>{ pfad.value+=(pfad.value?'>':'')+k; inp.value=k; if(ebene[k]){ebene=ebene[k]; zeige();} else c.remove(); };
      c.appendChild(r);});};
    zeige(); w.appendChild(c); };
  document.currentScript.parentNode.appendChild(w);
}
</script>
<script>dd('catalog', {'Herren': {'Kleidung': {'Jacken & Mäntel': null, 'Hosen': null}}, 'Damen': null})</script>
<script>dd('brand', {'Nike': null, 'Adidas': null})</script>
<script>dd('size', {'S': null, 'M': null, 'L': null})</script>
<script>dd('status', {'Neu mit Etikett': null, 'Sehr gut': null, 'Gut': null})</script>
<script>dd('color', {'Schwarz': null, 'Weiß': null})</script>
<input data-testid="price-input--input" name="price">
<label><input type="radio" name="paket" value="S">Klein</label><label><input type="radio" name="paket" value="M"><span>Mittel</span></label>
<button data-testid="upload-form-save-button" type="submit">Hochladen</button>
</form></body></html>"""


class MockSeiten:
    def __init__(self):
        self.gesendet: list[dict] = []
        self.statistik = {"viewCount": 12, "watchCount": 0}

    def route(self, route):
        url = urlparse(route.request.url)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        html = lambda body: route.fulfill(status=200, content_type="text/html; charset=utf-8", body=body)  # noqa: E731
        if url.path == "/p-anzeige-aufgeben-schritt2.html":
            return html(KA_FORM)
        if url.path == "/p-anzeige-bearbeiten.html":
            return html(KA_EDIT)
        if url.path == "/items/new":
            return html(VINTED_FORM)
        if url.path.endswith("/edit"):
            return html(VINTED_FORM.replace('action="/items/987654"', 'action="/items/987654/fertig"'))
        if url.path == "/m-meine-anzeigen-verwalten.json":
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"ads": [dict(id=4711, state="ACTIVE", **self.statistik)]}))
        if url.path.startswith("/api/v2/items/"):
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps({"item": {"view_count": 3, "favourite_count": 0}}))
        if q:
            self.gesendet.append({"pfad": url.path, **q})
        return html("<html><body>ok</body></html>")


@pytest.fixture
def umgebung(tmp_path):
    foto = tmp_path / "foto1.jpg"
    Image.new("RGB", (400, 300), "navy").save(foto)
    produkt = Produkt.model_validate(dict(
        id="jacke-001", name="Windbreaker Jacke", marke="Nike", preis=45, zustand="sehr_gut", groesse="M",
        farbe="Schwarz", notizen="Kleiner Fleck am Ärmel.", fotos=[foto],
        kleinanzeigen={"kategorie": ["Mode & Beauty", "Herrenbekleidung"], "preistyp": "VB"},
        vinted={"kategorie": ["Herren", "Kleidung", "Jacken & Mäntel"], "paketgroesse": "M"},
    ))
    konf = Konfiguration(postleitzahl="10115", kontakt_name="Haydar", auto_veroeffentlichen=True,
                         pause_zwischen_inseraten_s=10, datenordner=tmp_path / "daten",
                         ki=KiEinstellungen(aktiv=False), browser=BrowserEinstellungen(langsam_ms=0, timeout_ms=8000))
    mock = MockSeiten()
    with sync_playwright() as pw:
        def fabrik(pl):
            p = KLASSEN[pl](pw, konf)
            p.ctx.route("**/*", mock.route)
            return p
        yield konf, produkt, mock, fabrik


def test_kompletter_ablauf(umgebung, monkeypatch):
    konf, produkt, mock, fabrik = umgebung
    monkeypatch.setattr("verkaufsagent.agent.time.sleep", lambda s: None)
    zeit = [datetime(2026, 9, 1, 10, 0)]
    speicher = Speicher(konf.datenordner)
    agent = Agent(konf, [produkt], speicher, TextGenerator(konf.ki), fabrik, jetzt=lambda: zeit[0])
    try:
        assert agent.inseriere_neue() == 2

        ka = next(g for g in mock.gesendet if g["pfad"] == "/p-anzeige-aufgeben-bestaetigung.html")
        assert ka["title"].startswith("Nike Windbreaker Jacke")
        assert "Fleck" in ka["desc"] and ka["price"] == "45" and ka["priceType"] == "NEGOTIABLE"
        assert ka["cat"] == "Mode & Beauty>Herrenbekleidung"
        assert ka["attributeMap[kleidung.condition_s]"] == "like_new"
        assert ka["zip"] == "10115" and ka["ship"] == "ja" and ka["fotos"] == "foto1.jpg"

        vi = next(g for g in mock.gesendet if g["pfad"] == "/items/987654")
        assert vi["catalog_pfad"] == "Herren>Kleidung>Jacken & Mäntel"
        assert vi["status"] == "Sehr gut" and vi["brand"] == "Nike" and vi["size"] == "M"
        assert vi["price"] == "45" and vi["paket"] == "M" and "#nike" in vi["desc"]

        i_ka = speicher.hole("jacke-001", Plattform.kleinanzeigen)
        i_vi = speicher.hole("jacke-001", Plattform.vinted)
        assert (i_ka.status, i_ka.anzeige_id, i_ka.preis_aktuell) == ("online", "4711", 45)
        assert (i_vi.status, i_vi.anzeige_id) == ("online", "987654")

        # Zweiter Lauf inseriert nichts doppelt
        assert agent.inseriere_neue() == 0

        # Nach 3 Tagen: keine Reduzierung
        zeit[0] += timedelta(days=3)
        agent.pflege_inserate()
        assert speicher.hole("jacke-001", Plattform.kleinanzeigen).preis_aktuell == 45

        # Nach 15 Tagen mit schwacher Nachfrage: -5 %
        zeit[0] += timedelta(days=12)
        agent.pflege_inserate()
        i_ka = speicher.hole("jacke-001", Plattform.kleinanzeigen)
        assert i_ka.preis_aktuell == 42 and i_ka.aufrufe == 12
        assert any(g["pfad"] == "/m-meine-anzeigen.html" and g["price"] == "42" for g in mock.gesendet)
        assert speicher.hole("jacke-001", Plattform.vinted).preis_aktuell == 42

        # Viele Favoriten -> keine weitere Reduzierung, auch nach Wochen
        mock.statistik = {"viewCount": 300, "watchCount": 9}
        zeit[0] += timedelta(days=30)
        agent.pflege_inserate()
        assert speicher.hole("jacke-001", Plattform.kleinanzeigen).preis_aktuell == 42
    finally:
        agent.schliessen()


def test_fehlende_kategorie_wird_als_fehler_gespeichert(umgebung):
    konf, produkt, mock, fabrik = umgebung
    produkt.plattformen = [Plattform.vinted]
    produkt.vinted.kategorie = ["Herren", "Gibt es nicht"]
    speicher = Speicher(konf.datenordner)
    agent = Agent(konf, [produkt], speicher, TextGenerator(konf.ki), fabrik)
    try:
        assert agent.inseriere_neue() == 0
        i = speicher.hole("jacke-001", Plattform.vinted)
        assert i.status == "fehler" and "nicht auswählbar" in i.fehler
        assert not [g for g in mock.gesendet if g["pfad"] == "/items/987654"]
    finally:
        agent.schliessen()
