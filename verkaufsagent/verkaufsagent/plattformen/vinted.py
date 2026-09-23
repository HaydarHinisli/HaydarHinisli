"""Vinted.de – Inserieren, Preis ändern, Statistik lesen."""
from __future__ import annotations

import logging
import re

from ..modelle import Inserat, Plattform, Produkt, Texte
from .basis import NichtAngemeldet, PlattformBasis, PlattformFehler, Statistik, Veroeffentlicht, preis_text

log = logging.getLogger(__name__)

BASIS = "https://www.vinted.de"
PAKET = {"S": "Klein", "M": "Mittel", "L": "Groß"}


class Vinted(PlattformBasis):
    plattform = Plattform.vinted
    startseite = BASIS

    def ist_angemeldet(self) -> bool:
        self.page.goto(f"{BASIS}/items/new")
        self.page.wait_for_load_state("domcontentloaded")
        if "signup" in self.page.url or "login" in self.page.url:
            return False
        return self.optional("fotos", 8000, sichtbar=False) is not None

    def _auswahl(self, feld: str, pfad: list[str], pflicht: bool) -> None:
        """Öffnet ein Vinted-Dropdown und klickt sich durch die Einträge."""
        if not pfad:
            return
        eingabe = self.finde(feld) if pflicht else self.optional(feld)
        if eingabe is None:
            return
        eingabe.click()
        try:
            for ebene in pfad:
                inhalt = self.finde("dropdown_inhalt", 5000)
                inhalt.get_by_text(ebene, exact=True).first.click(timeout=5000)
                self.page.wait_for_timeout(400)
        except Exception as e:
            if pflicht:
                raise PlattformFehler(f"Vinted-{feld} '{' > '.join(pfad)}' nicht auswählbar: {e}") from e
            log.warning("Vinted-%s '%s' nicht gesetzt: %s", feld, " > ".join(pfad), e)
            self.page.keyboard.press("Escape")

    def _marke(self, marke: str | None) -> None:
        """Marke ist optional – Probleme hier brechen das Inserat nie ab."""
        if not marke:
            return
        feld = self.optional("marke")
        if not feld:
            return
        try:
            feld.click()
            suche = self.optional("marke_suche", 3000)
            if suche is not None:
                suche.fill(marke)
            elif feld.is_editable():
                feld.fill(marke)
            self.page.wait_for_timeout(1200)
            inhalt = self.finde("dropdown_inhalt", 3000)
            treffer = inhalt.get_by_text(marke, exact=True).first
            if not treffer.count():
                # z. B. "<Marke> als Marke verwenden"
                treffer = inhalt.get_by_text(re.compile(re.escape(marke), re.I)).first
            treffer.click(timeout=3000)
        except Exception as e:
            log.warning("Marke '%s' auf Vinted nicht gesetzt: %s", marke, e)
            self.page.keyboard.press("Escape")

    def veroeffentliche(self, produkt: Produkt, texte: Texte, preis: float) -> Veroeffentlicht:
        if not produkt.fotos:
            raise PlattformFehler("Vinted verlangt mindestens ein Foto")
        if not produkt.vinted.kategorie:
            raise PlattformFehler("Für Vinted muss 'vinted.kategorie' im Produkt angegeben sein")
        self.page.goto(f"{BASIS}/items/new")
        if "signup" in self.page.url or "login" in self.page.url:
            raise NichtAngemeldet("Nicht bei Vinted angemeldet – 'verkaufsagent anmelden vinted' ausführen")
        self.cookies_akzeptieren()

        self.finde("fotos", sichtbar=False).set_input_files([str(f) for f in produkt.fotos[:20]])
        self.page.wait_for_timeout(2000 + 1500 * min(len(produkt.fotos), 20))

        self.finde("titel").fill(texte.titel)
        self.finde("beschreibung").fill(texte.beschreibung)
        self._auswahl("kategorie", produkt.vinted.kategorie, pflicht=True)
        self._marke(produkt.marke)
        if produkt.groesse:
            self._auswahl("groesse", [produkt.groesse], pflicht=False)
        self._auswahl("zustand", [produkt.zustand.text], pflicht=True)
        if produkt.farbe:
            self._auswahl("farbe", [produkt.farbe.split("/")[0].strip().capitalize()], pflicht=False)

        self.finde("preis").fill(preis_text(preis))
        paket = self.page.get_by_text(PAKET[produkt.vinted.paketgroesse], exact=True).first
        if paket.count():
            paket.click()

        self.bestaetigen_oder_abbrechen(produkt)
        self.finde("absenden").click()
        self.page.wait_for_url(re.compile(r"/items/\d+"), timeout=90000)
        anzeige_id = re.search(r"/items/(\d+)", self.page.url).group(1)
        return Veroeffentlicht(anzeige_id, f"{BASIS}/items/{anzeige_id}")

    def aendere_preis(self, inserat: Inserat, preis: float) -> None:
        self.page.goto(f"{BASIS}/items/{inserat.anzeige_id}/edit")
        if "signup" in self.page.url or "login" in self.page.url:
            raise NichtAngemeldet("Nicht bei Vinted angemeldet")
        self.cookies_akzeptieren()
        self.finde("preis").fill(preis_text(preis))
        self.finde("absenden").click()
        self.page.wait_for_url(lambda url: "/edit" not in url, timeout=60000)

    def lese_statistik(self, inserat: Inserat) -> Statistik:
        stat = Statistik()
        status, daten = self.hole_json(f"{BASIS}/api/v2/items/{inserat.anzeige_id}")
        if status in (404, 410):
            stat.aktiv = False
            return stat
        if daten:
            item = daten.get("item", {})
            stat.aufrufe = item.get("view_count")
            stat.favoriten = item.get("favourite_count")
            if item.get("is_closed") or item.get("is_sold") or item.get("is_hidden"):
                stat.aktiv = False
        else:
            log.debug("Vinted-Statistik nicht lesbar (HTTP %s)", status)
        return stat
