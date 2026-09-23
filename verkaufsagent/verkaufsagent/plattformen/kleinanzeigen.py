"""Kleinanzeigen.de – Inserieren, Preis ändern, Statistik lesen."""
from __future__ import annotations

import logging
import re

from ..modelle import Inserat, Plattform, Produkt, Texte, Zustand
from .basis import NichtAngemeldet, PlattformBasis, PlattformFehler, Statistik, Veroeffentlicht, preis_text

log = logging.getLogger(__name__)

BASIS = "https://www.kleinanzeigen.de"
ZUSTAND_WERTE = {
    Zustand.neu_mit_etikett: ["new_with_tag", "new", "Neu"],
    Zustand.neu: ["new", "Neu"],
    Zustand.sehr_gut: ["like_new", "very_good", "Sehr Gut", "Sehr gut"],
    Zustand.gut: ["good", "ok", "Gut"],
    Zustand.zufriedenstellend: ["alright", "ok", "In Ordnung"],
}


class Kleinanzeigen(PlattformBasis):
    plattform = Plattform.kleinanzeigen
    startseite = f"{BASIS}/m-einloggen.html"

    def ist_angemeldet(self) -> bool:
        self.page.goto(f"{BASIS}/m-meine-anzeigen.html")
        self.page.wait_for_load_state("domcontentloaded")
        return "einloggen" not in self.page.url and "login" not in self.page.url

    def veroeffentliche(self, produkt: Produkt, texte: Texte, preis: float) -> Veroeffentlicht:
        if not self.konf.postleitzahl:
            raise PlattformFehler("postleitzahl in config.yaml fehlt (Pflicht bei Kleinanzeigen)")
        self.page.goto(f"{BASIS}/p-anzeige-aufgeben-schritt2.html")
        if "einloggen" in self.page.url:
            raise NichtAngemeldet("Nicht bei Kleinanzeigen angemeldet – 'verkaufsagent anmelden kleinanzeigen' ausführen")
        self.cookies_akzeptieren()

        self.finde("titel").fill(texte.titel)
        self._kategorie(produkt)
        self.finde("beschreibung").fill(texte.beschreibung)

        self.finde("preis").fill(preis_text(preis))
        typ = self.optional("preistyp")
        if typ:
            typ.select_option("NEGOTIABLE" if produkt.kleinanzeigen.preistyp == "VB" else "FIXED")

        self._zustand(produkt)
        versand = self.optional("versand_ja" if produkt.versand else "versand_nein", 2000)
        if versand:
            versand.check() if versand.get_attribute("type") in ("radio", "checkbox") else versand.click()

        if produkt.fotos:
            self.finde("fotos", sichtbar=False).set_input_files([str(f) for f in produkt.fotos[:20]])
            self.page.wait_for_timeout(2000 + 1500 * min(len(produkt.fotos), 20))

        plz = self.finde("plz")
        if not plz.input_value():
            plz.fill(self.konf.postleitzahl)
        name = self.optional("name")
        if name and self.konf.kontakt_name and not name.input_value():
            name.fill(self.konf.kontakt_name)

        self.bestaetigen_oder_abbrechen(produkt)
        self.finde("absenden").click()
        self.page.wait_for_url(re.compile(r"adId=\d+|bestaetigung|s-anzeige"), timeout=60000)
        treffer = re.search(r"adId=(\d+)", self.page.url) or re.search(r"/(\d+)-\d+-\d+", self.page.url)
        if not treffer:
            raise PlattformFehler(f"Anzeigen-ID nicht erkannt (URL: {self.page.url})")
        anzeige_id = treffer.group(1)
        return Veroeffentlicht(anzeige_id, f"{BASIS}/s-anzeige/{anzeige_id}")

    def _kategorie(self, produkt: Produkt) -> None:
        pfad = produkt.kleinanzeigen.kategorie
        if pfad:
            self.finde("kategorie_aendern").click()
            for ebene in pfad:
                self.page.get_by_text(ebene, exact=True).first.click()
                self.page.wait_for_timeout(500)
            self.finde("kategorie_weiter").click()
            self.finde("titel")  # zurück im Formular
        else:
            # Kleinanzeigen schlägt nach Eingabe des Titels eine Kategorie vor
            self.page.keyboard.press("Tab")
            self.page.wait_for_timeout(2500)
        anzeige = self.optional("kategorie_anzeige", 5000, sichtbar=False)
        if anzeige is None or not (anzeige.inner_text() or "").strip():
            raise PlattformFehler("Keine Kategorie gesetzt – bitte 'kleinanzeigen.kategorie' im Produkt angeben")

    def _zustand(self, produkt: Produkt) -> None:
        feld = self.optional("zustand", 2000)
        if not feld or (feld.evaluate("e => e.tagName") or "").lower() != "select":
            return  # Kategorie ohne Zustandsfeld
        for wert in ZUSTAND_WERTE[produkt.zustand]:
            for art in ("value", "label"):
                try:
                    feld.select_option(**{art: wert}, timeout=1000)
                    return
                except Exception:
                    continue
        log.warning("Zustand '%s' konnte nicht gewählt werden", produkt.zustand.text)

    def aendere_preis(self, inserat: Inserat, preis: float) -> None:
        self.page.goto(f"{BASIS}/p-anzeige-bearbeiten.html?adId={inserat.anzeige_id}")
        if "einloggen" in self.page.url:
            raise NichtAngemeldet("Nicht bei Kleinanzeigen angemeldet")
        self.cookies_akzeptieren()
        self.finde("preis").fill(preis_text(preis))
        self.finde("absenden").click()
        self.page.wait_for_load_state("networkidle")

    def lese_statistik(self, inserat: Inserat) -> Statistik:
        stat = Statistik()
        # 1) Eigene Anzeigenliste (JSON, nur angemeldet) – enthält Aufrufe/Merkliste
        try:
            _, daten = self.hole_json(f"{BASIS}/m-meine-anzeigen-verwalten.json?sort=DEFAULT")
            if daten:
                for ad in daten.get("ads", []):
                    if str(ad.get("id")) == inserat.anzeige_id:
                        stat.aufrufe = _zahl(ad, "viewCount", "views", "visits")
                        stat.favoriten = _zahl(ad, "watchCount", "watchlistCount", "favorites")
                        stat.nachrichten = _zahl(ad, "messageCount", "replyCount")
                        status = str(ad.get("state", ad.get("status", "active"))).lower()
                        stat.aktiv = status in ("active", "aktiv", "paused")
                        return stat
        except Exception as e:
            log.debug("Kleinanzeigen-JSON nicht lesbar: %s", e)
        # 2) Öffentliche Anzeigenseite – Besucherzähler
        antwort = self.page.goto(f"{BASIS}/s-anzeige/{inserat.anzeige_id}")
        if (antwort is not None and antwort.status in (404, 410)) or "m-anzeige-nicht-gefunden" in self.page.url:
            stat.aktiv = False
            return stat
        zaehler = self.optional("aufrufe", 5000, sichtbar=False)
        if zaehler:
            stat.aufrufe = _int(zaehler.inner_text())
        return stat


def _zahl(d: dict, *schluessel: str) -> int | None:
    for s in schluessel:
        if isinstance(d.get(s), (int, float)):
            return int(d[s])
    return None


def _int(text: str) -> int | None:
    ziffern = re.sub(r"\D", "", text or "")
    return int(ziffern) if ziffern else None
