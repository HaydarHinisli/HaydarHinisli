from datetime import datetime, timedelta

import pytest

from verkaufsagent.konfiguration import PreisRegeln
from verkaufsagent.modelle import Inserat, Plattform, Produkt
from verkaufsagent.preise import bewerte_angebot, pruefe_reduzierung, schoener_preis

JETZT = datetime(2026, 9, 23, 12, 0)


def produkt(**kw):
    daten = dict(id="p1", name="Jacke", preis=100, zustand="gut")
    daten.update(kw)
    return Produkt.model_validate(daten)


def inserat(tage, preis=100.0, **kw):
    return Inserat(produkt_id="p1", plattform=Plattform.vinted, status="online",
                   online_seit=JETZT - timedelta(days=tage), preis_aktuell=preis, **kw)


def statistik(aufrufe, favoriten=0, nachrichten=0):
    return dict(aufrufe=aufrufe, favoriten=favoriten, nachrichten=nachrichten, statistik_stand=JETZT - timedelta(hours=1))


def test_untergrenze_max_30_prozent():
    assert produkt().untergrenze() == 70
    assert produkt(max_rabatt_prozent=10).untergrenze() == 90
    assert produkt(mindestpreis=85).untergrenze() == 85
    assert produkt(mindestpreis=50).untergrenze() == 70  # Mindestpreis darf die 30 % nicht aushebeln
    assert produkt(verhandelbar=False).untergrenze() == 100


def test_max_rabatt_ueber_30_wird_abgelehnt():
    with pytest.raises(ValueError):
        produkt(max_rabatt_prozent=40)


def test_keine_reduzierung_zu_frueh():
    e = pruefe_reduzierung(produkt(), inserat(5, **statistik(0)), PreisRegeln(), JETZT)
    assert e.neuer_preis is None


def test_reduzierung_bei_schwacher_nachfrage():
    e = pruefe_reduzierung(produkt(), inserat(15, **statistik(10)), PreisRegeln(), JETZT)
    assert e.neuer_preis == 95


def test_keine_reduzierung_bei_hohem_interesse():
    regeln = PreisRegeln()
    assert pruefe_reduzierung(produkt(), inserat(30, **statistik(10, favoriten=6)), regeln, JETZT).neuer_preis is None
    assert pruefe_reduzierung(produkt(), inserat(30, **statistik(10, nachrichten=3)), regeln, JETZT).neuer_preis is None
    assert pruefe_reduzierung(produkt(), inserat(30, **statistik(200, favoriten=2)), regeln, JETZT).neuer_preis is None


def test_abstand_zwischen_reduzierungen():
    i = inserat(30, preis=95, letzte_preisaenderung=JETZT - timedelta(days=3), **statistik(10))
    assert pruefe_reduzierung(produkt(), i, PreisRegeln(), JETZT).neuer_preis is None
    i.letzte_preisaenderung = JETZT - timedelta(days=8)
    assert pruefe_reduzierung(produkt(), i, PreisRegeln(), JETZT).neuer_preis == 90


def test_nie_unter_untergrenze_auch_nach_vielen_runden():
    p = produkt(preis=47.99)
    i = inserat(14, preis=47.99)
    regeln = PreisRegeln()
    t = JETZT
    preise = []
    for _ in range(20):
        i.aufrufe, i.favoriten, i.statistik_stand = 1, 0, t
        e = pruefe_reduzierung(p, i, regeln, t)
        if e.neuer_preis:
            assert e.neuer_preis < i.preis_aktuell
            i.preis_aktuell, i.letzte_preisaenderung = e.neuer_preis, t
            preise.append(e.neuer_preis)
        t += timedelta(days=8)
    assert preise, "es sollte reduziert worden sein"
    assert min(preise) >= p.untergrenze() >= 47.99 * 0.7


def test_ohne_statistik_hoechstens_15_prozent():
    p, i, t = produkt(), inserat(14), JETZT
    for _ in range(10):
        e = pruefe_reduzierung(p, i, PreisRegeln(), t)
        if e.neuer_preis:
            i.preis_aktuell, i.letzte_preisaenderung = e.neuer_preis, t
        t += timedelta(days=8)
    assert i.preis_aktuell == 85


def test_festpreis_nie_reduziert():
    e = pruefe_reduzierung(produkt(verhandelbar=False), inserat(90, **statistik(0)), PreisRegeln(), JETZT)
    assert e.neuer_preis is None


def test_schoener_preis():
    assert schoener_preis(47.3, 40) == 47
    assert schoener_preis(33.59, 33.59) == 34  # aufrunden statt Untergrenze verletzen
    assert schoener_preis(4.8, 1) == 4.5
    assert schoener_preis(237, 200) == 235


@pytest.mark.parametrize("angebot,aktion", [(100, "annehmen"), (96, "annehmen"), (85, "gegenangebot"), (40, "gegenangebot")])
def test_angebote(angebot, aktion):
    b = bewerte_angebot(produkt(), 100, angebot, tage_online=2)
    assert b.aktion == aktion
    assert b.betrag >= 70


def test_angebot_nie_unter_untergrenze_auch_spaet():
    b = bewerte_angebot(produkt(), 100, 60, tage_online=365)
    assert b.aktion == "gegenangebot" and b.betrag >= 70
    assert bewerte_angebot(produkt(), 100, 71, tage_online=365).aktion == "annehmen"
