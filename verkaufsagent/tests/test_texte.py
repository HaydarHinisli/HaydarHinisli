import json
from types import SimpleNamespace

import anthropic

from verkaufsagent.konfiguration import KiEinstellungen
from verkaufsagent.modelle import Plattform, Produkt
from verkaufsagent.texte import TextGenerator, pruefe_texte, vorlage


def produkt(**kw):
    d = dict(id="p1", name="Windbreaker Jacke", marke="Nike", preis=45, zustand="sehr_gut",
             groesse="M", farbe="Schwarz", notizen="Kleiner Fleck am linken Ärmel.")
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


def test_vorlage_ist_vollstaendig_und_gueltig():
    p = produkt()
    for pl in Plattform:
        t = vorlage(p, pl)
        assert pruefe_texte(t, pl, p) == []
        assert "Fleck" in t.beschreibung  # Mängel werden immer genannt
        assert "Sehr gut" in t.beschreibung
        assert t.titel.startswith("Nike")


def test_ki_texte_werden_uebernommen():
    beschreibung = "Schöne Nike Windbreaker Jacke in Größe M, Farbe Schwarz. Zustand sehr gut, nur ein kleiner Fleck am linken Ärmel."
    client = FakeClient({"kleinanzeigen": {"titel": "Nike Windbreaker Jacke Gr. M schwarz", "beschreibung": beschreibung},
                         "vinted": {"titel": "Nike Windbreaker M schwarz", "beschreibung": beschreibung + "\n#nike #windbreaker"}})
    texte = TextGenerator(KiEinstellungen(), client).erzeuge(produkt())
    assert texte[Plattform.kleinanzeigen].quelle == "ki"
    assert texte[Plattform.vinted].beschreibung.endswith("#windbreaker")
    req = client.aufrufe[0]
    assert req["model"] == "claude-opus-5"
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert "Fleck" in req["messages"][0]["content"][-1]["text"]


def test_fallback_bei_api_fehler():
    fehler = anthropic.APIConnectionError(request=None)  # type: ignore[arg-type]
    texte = TextGenerator(KiEinstellungen(), FakeClient(fehler=fehler)).erzeuge(produkt())
    assert all(t.quelle == "vorlage" for t in texte.values())


def test_fallback_bei_unvollstaendiger_ki_antwort():
    client = FakeClient({"kleinanzeigen": {"titel": "Jacke", "beschreibung": "kurz"},
                         "vinted": {"titel": "Jacke", "beschreibung": "kurz"}})
    texte = TextGenerator(KiEinstellungen(), client).erzeuge(produkt())
    assert all(t.quelle == "vorlage" for t in texte.values())


def test_pruefung_erkennt_preis_und_links():
    p = produkt()
    t = vorlage(p, Plattform.kleinanzeigen)
    t.beschreibung += " Nur 40 € – mehr auf http://x.de"
    assert "Beschreibung enthält Preis, Link oder E-Mail" in pruefe_texte(t, Plattform.kleinanzeigen, p)
