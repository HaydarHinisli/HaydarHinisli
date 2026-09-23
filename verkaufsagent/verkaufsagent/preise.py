"""Preislogik.

Grundsätze:
  * Inseriert wird immer exakt zum vorgegebenen Preis.
  * Reduziert wird nur, wenn ALLE Bedingungen erfüllt sind (Zeit online,
    Abstand zur letzten Reduzierung, schwache Nachfrage).
  * Der Preis fällt nie unter Produkt.untergrenze() – maximal 30 % unter dem
    Originalpreis, nie unter einem gesetzten Mindestpreis.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .konfiguration import PreisRegeln
from .modelle import MAX_RABATT_ABSOLUT, Inserat, Produkt


@dataclass
class PreisEntscheidung:
    neuer_preis: float | None  # None = unverändert lassen
    grund: str


def schoener_preis(betrag: float, untergrenze: float) -> float:
    """Rundet auf einen marktüblichen Preis, ohne die Untergrenze zu unterschreiten."""
    if betrag < 10:
        schritt = 0.5
    elif betrag < 100:
        schritt = 1.0
    elif betrag < 500:
        schritt = 5.0
    else:
        schritt = 10.0
    gerundet = math.floor(betrag / schritt) * schritt
    if gerundet < untergrenze:
        gerundet = math.ceil(untergrenze / schritt) * schritt
    return round(gerundet, 2)


def _statistik_aktuell(inserat: Inserat, regeln: PreisRegeln, jetzt: datetime) -> bool:
    return (
        inserat.statistik_stand is not None
        and jetzt - inserat.statistik_stand <= timedelta(hours=regeln.statistik_max_alter_stunden)
        and inserat.aufrufe is not None
    )


def pruefe_reduzierung(produkt: Produkt, inserat: Inserat, regeln: PreisRegeln, jetzt: datetime) -> PreisEntscheidung:
    if not produkt.verhandelbar:
        return PreisEntscheidung(None, "Produkt ist als nicht verhandelbar markiert")
    if inserat.status != "online" or inserat.online_seit is None or inserat.preis_aktuell is None:
        return PreisEntscheidung(None, "Inserat ist nicht online")

    tage_online = (jetzt - inserat.online_seit).total_seconds() / 86400
    if tage_online < regeln.erste_reduzierung_nach_tagen:
        return PreisEntscheidung(None, f"erst {tage_online:.1f} von {regeln.erste_reduzierung_nach_tagen} Tagen online")

    if inserat.letzte_preisaenderung is not None:
        seit = (jetzt - inserat.letzte_preisaenderung).total_seconds() / 86400
        if seit < regeln.abstand_tage:
            return PreisEntscheidung(None, f"letzte Reduzierung vor {seit:.1f} Tagen (Mindestabstand {regeln.abstand_tage})")

    # Nachfrage prüfen
    max_rabatt = min(produkt.max_rabatt_prozent / 100, MAX_RABATT_ABSOLUT)
    if _statistik_aktuell(inserat, regeln, jetzt):
        if (inserat.favoriten or 0) >= regeln.favoriten_hoch:
            return PreisEntscheidung(None, f"hohes Interesse ({inserat.favoriten} Favoriten)")
        if (inserat.nachrichten or 0) >= regeln.nachrichten_hoch:
            return PreisEntscheidung(None, f"hohes Interesse ({inserat.nachrichten} Nachrichten)")
        aufrufe_pro_tag = (inserat.aufrufe or 0) / max(tage_online, 1)
        if aufrufe_pro_tag >= regeln.aufrufe_pro_tag_schwach and (inserat.favoriten or 0) > 0:
            return PreisEntscheidung(None, f"Nachfrage ausreichend ({aufrufe_pro_tag:.1f} Aufrufe/Tag, Favoriten vorhanden)")
        nachfrage = f"schwache Nachfrage ({aufrufe_pro_tag:.1f} Aufrufe/Tag, {inserat.favoriten or 0} Favoriten)"
    else:
        max_rabatt = min(max_rabatt, regeln.max_rabatt_ohne_statistik)
        nachfrage = "keine aktuelle Statistik – vorsichtige Reduzierung"

    # Nächste Stufe bestimmen: kleinste Stufe, die günstiger ist als der aktuelle Preis
    untergrenze = max(produkt.untergrenze(), round(produkt.preis * (1 - max_rabatt), 2))
    for stufe in sorted(s for s in regeln.stufen if 0 < s <= MAX_RABATT_ABSOLUT):
        if stufe > max_rabatt + 1e-9:
            break
        kandidat = schoener_preis(produkt.preis * (1 - stufe), untergrenze)
        if kandidat < inserat.preis_aktuell - 0.001:
            kandidat = max(kandidat, untergrenze)
            return PreisEntscheidung(kandidat, f"{tage_online:.0f} Tage online, {nachfrage}; Stufe -{stufe:.0%}")
    return PreisEntscheidung(None, "Untergrenze erreicht – keine weitere Reduzierung")


@dataclass
class AngebotsBewertung:
    aktion: str  # annehmen | gegenangebot | ablehnen
    betrag: float | None
    begruendung: str


def bewerte_angebot(produkt: Produkt, aktueller_preis: float, angebot: float, tage_online: float) -> AngebotsBewertung:
    """Bewertet ein Käuferangebot. Der Spielraum wächst langsam mit der Standzeit."""
    untergrenze = produkt.untergrenze()
    if angebot >= aktueller_preis:
        return AngebotsBewertung("annehmen", aktueller_preis, "Angebot entspricht dem Preis")
    if not produkt.verhandelbar:
        return AngebotsBewertung("ablehnen", aktueller_preis, "Festpreis")
    # Spielraum: 5 % in der ersten Woche, dann +5 % je Woche, gedeckelt durch die Untergrenze
    spielraum = min(0.05 + 0.05 * int(tage_online // 7), MAX_RABATT_ABSOLUT)
    akzeptabel_ab = max(untergrenze, schoener_preis(aktueller_preis * (1 - spielraum), untergrenze))
    if angebot >= akzeptabel_ab:
        return AngebotsBewertung("annehmen", round(angebot, 2), f"liegt im Spielraum (ab {akzeptabel_ab:.2f} €)")
    if angebot < untergrenze * 0.8:
        return AngebotsBewertung(
            "gegenangebot", max(akzeptabel_ab, untergrenze),
            f"Angebot deutlich zu niedrig (Untergrenze {untergrenze:.2f} €)",
        )
    gegen = max(akzeptabel_ab, schoener_preis((angebot + aktueller_preis) / 2, untergrenze))
    return AngebotsBewertung("gegenangebot", min(gegen, aktueller_preis), "Mitte zwischen Angebot und Preis, nie unter Untergrenze")
