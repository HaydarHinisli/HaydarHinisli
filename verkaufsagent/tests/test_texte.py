import json
from types import SimpleNamespace

import anthropic

from verkaufsagent.konfiguration import KiEinstellungen
from verkaufsagent.modelle import Produkt
from verkaufsagent.plattformdef import Definition
from verkaufsagent.texte import TextGenerator, pruefe_texte, vorlage

DEFS = {
    "crazyslip": Definition(name="crazyslip", anzeigename="Crazyslip", basis_url="https://x", stil="dezent"),
    "creamsi": Definition(name="creamsi", anzeigename="Creamsi", basis_url="https://y", titel_max=40),
}


def produkt(**kw):
    d = dict(id="p1", name="Spitzenslip", marke="Hunkemöller", preis=25, groesse="M", farbe="Schwarz",
             notizen="Kleine Naht offen.", crazyslip={"felder": {"tragedauer": "1 Tag"}})
    d.update(kw)
    return Produkt.model_validate(d)


class FakeClient:
    def __init__(self, antwort=None, fehler=None):
        self.aufrufe = []
        self.antwort, self.fehler = antwort, fehler
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.aufrufe.append(kw)
        if self.fehler:
            raise self.fehler
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(self.antwort))])


def test_produkt_optionen_und_standardwerte():
    p = produkt()
    assert p.plattformen == ["crazyslip", "creamsi"]
    assert p.zustand.text == "Getragen"
    assert p.optionen_fuer("crazyslip").felder == {"tragedauer": "1 Tag"}
    assert p.optionen_fuer("creamsi").felder == {}


def test_vorlage_ist_vollstaendig_und_gueltig():
    p = produkt()
    for pl, d in DEFS.items():
        t = vorlage(p, pl, d)
        assert pruefe_texte(t, d) == [], (pl, t)
        assert "Naht" in t.beschreibung and "diskret" in t.beschreibung
    assert "Tragedauer: 1 Tag" in vorlage(p, "crazyslip", DEFS["crazyslip"]).beschreibung
    assert len(vorlage(p, "creamsi", DEFS["creamsi"]).titel) <= 40


def test_ki_texte_pro_plattform():
    b = "Schwarzer Spitzenslip von Hunkemöller in Größe M, einen Tag getragen. Kleine Naht offen. Diskreter Versand."
    client = FakeClient({"crazyslip": {"titel": "Hunkemöller Spitzenslip M schwarz", "beschreibung": b},
                         "creamsi": {"titel": "Spitzenslip Gr. M schwarz", "beschreibung": b}})
    texte = TextGenerator(KiEinstellungen(), DEFS.__getitem__, client).erzeuge(produkt())
    assert set(texte) == {"crazyslip", "creamsi"} and all(t.quelle == "ki" for t in texte.values())
    req = client.aufrufe[0]
    assert req["model"] == "claude-opus-5"
    assert set(req["output_config"]["format"]["schema"]["required"]) == {"crazyslip", "creamsi"}
    prompt = req["messages"][0]["content"][-1]["text"]
    assert "Tragedauer: 1 Tag" in prompt and "Naht" in prompt and "dezent" in prompt
    assert "keine expliziten" in req["system"]


def test_fallback_bei_api_fehler():
    fehler = anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
    texte = TextGenerator(KiEinstellungen(), DEFS.__getitem__, FakeClient(fehler=fehler)).erzeuge(produkt())
    assert all(t.quelle == "vorlage" for t in texte.values())


def test_fallback_bei_unvollstaendiger_ki_antwort():
    client = FakeClient({"crazyslip": {"titel": "Slip", "beschreibung": "kurz"}, "creamsi": {"titel": "Slip", "beschreibung": "kurz"}})
    texte = TextGenerator(KiEinstellungen(), DEFS.__getitem__, client).erzeuge(produkt())
    assert all(t.quelle == "vorlage" for t in texte.values())


def test_pruefung_erkennt_preis_und_links():
    t = vorlage(produkt(), "crazyslip", DEFS["crazyslip"])
    t.beschreibung += " Nur 20 € – mehr auf http://x.de"
    assert "Beschreibung enthält Preis, Link oder E-Mail" in pruefe_texte(t, DEFS["crazyslip"])
