"""Übernimmt ein bereits von Hand erstelltes Vinted-Inserat in den Agenten.

Das Inserat wird NICHT neu hochgeladen. Der Agent kennt es danach und
kümmert sich um Statistik und Preispflege; optional wird es zusätzlich
auf Kleinanzeigen eingestellt.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import yaml

from .konfiguration import lade_produkte
from .modelle import Inserat, Plattform, Produkt, Zustand
from .plattformen.vinted import VintedArtikel
from .speicher import Speicher

log = logging.getLogger(__name__)

_ZUSTAENDE = {
    "neu mit etikett": Zustand.neu_mit_etikett,
    "neu ohne etikett": Zustand.neu,
    "neu": Zustand.neu,
    "sehr gut": Zustand.sehr_gut,
    "gut": Zustand.gut,
    "zufriedenstellend": Zustand.zufriedenstellend,
}


def zustand_aus_text(text: str | None) -> Zustand | None:
    return _ZUSTAENDE.get((text or "").strip().lower())


def baue_produkt(artikel: VintedArtikel, produkt_id: str, fotos: list[Path], basis: Path, *,
                 preis: float | None, mindestpreis: float | None, zustand: Zustand | None,
                 kleinanzeigen: bool, ka_kategorie: list[str]) -> dict:
    """Erzeugt den Eintrag für produkte.yaml."""
    grundpreis = preis or artikel.preis
    if not grundpreis:
        raise ValueError("Preis des Inserats nicht lesbar – bitte mit --preis angeben")
    zustand = zustand or zustand_aus_text(artikel.zustand)
    if zustand is None:
        raise ValueError(f"Zustand '{artikel.zustand}' nicht erkannt – bitte mit --zustand angeben")

    eintrag: dict = {
        "id": produkt_id,
        "name": artikel.titel,
        "preis": grundpreis,
        "zustand": zustand.value,
    }
    if mindestpreis:
        eintrag["mindestpreis"] = mindestpreis
    for feld in ("marke", "groesse", "farbe"):
        wert = getattr(artikel, feld)
        if wert:
            eintrag[feld] = wert
    if artikel.beschreibung:
        # Deine eigenen Angaben aus Vinted – dienen als Fakten für neue Texte (z. B. Kleinanzeigen)
        eintrag["notizen"] = artikel.beschreibung
    ordner = fotos[0].parent if fotos else None
    if ordner is not None:
        try:
            eintrag["fotos"] = [str(ordner.relative_to(basis))]
        except ValueError:
            eintrag["fotos"] = [str(ordner)]
    eintrag["plattformen"] = ["vinted", "kleinanzeigen"] if kleinanzeigen else ["vinted"]
    if kleinanzeigen and ka_kategorie:
        eintrag["kleinanzeigen"] = {"kategorie": ka_kategorie}
    eintrag["vinted_url"] = artikel.url  # nur zur Info
    return eintrag


def trage_ein(produkte_datei: Path, eintrag: dict) -> Produkt:
    """Hängt das Produkt an produkte.yaml an (Kommentare bleiben erhalten) und prüft das Ergebnis."""
    alt = produkte_datei.read_text(encoding="utf-8") if produkte_datei.exists() else ""
    daten = yaml.safe_load(alt) if alt.strip() else None
    if daten and any(p.get("id") == eintrag["id"] for p in daten.get("produkte") or []):
        raise ValueError(f"Produkt '{eintrag['id']}' steht schon in {produkte_datei.name}")

    block = yaml.safe_dump([eintrag], allow_unicode=True, sort_keys=False, width=1000)
    block = "".join("  " + z if z.strip() else z for z in block.splitlines(keepends=True))
    if not daten or "produkte" not in daten:
        neu = alt.rstrip() + ("\n\n" if alt.strip() else "") + "produkte:\n" + block
    else:
        neu = alt.rstrip("\n") + "\n\n" + block
    produkte_datei.write_text(neu, encoding="utf-8")
    try:
        produkt = next((p for p in lade_produkte(produkte_datei) if p.id == eintrag["id"]), None)
        if produkt is None:
            raise ValueError(f"Eintrag konnte nicht an {produkte_datei.name} angehängt werden "
                             "('produkte:' muss der letzte Abschnitt der Datei sein)")
    except Exception:
        produkte_datei.write_text(alt, encoding="utf-8")  # nichts kaputt machen
        raise
    return produkt


def registriere_inserat(speicher: Speicher, produkt: Produkt, artikel: VintedArtikel, jetzt: datetime) -> Inserat:
    """Legt das bestehende Vinted-Inserat als 'online' an – so wird es nie doppelt hochgeladen."""
    inserat = Inserat(
        produkt_id=produkt.id, plattform=Plattform.vinted,
        status="online" if artikel.aktiv else "entfernt",
        anzeige_id=artikel.anzeige_id, url=artikel.url,
        titel=artikel.titel, beschreibung=artikel.beschreibung,
        preis_aktuell=artikel.preis or produkt.preis,
        # Standzeit zählt ab der echten Erstellung – sonst ab heute
        online_seit=artikel.erstellt or jetzt,
        aufrufe=artikel.aufrufe, favoriten=artikel.favoriten,
        statistik_stand=jetzt if artikel.aufrufe is not None else None,
    )
    speicher.speichere(inserat)
    return inserat
