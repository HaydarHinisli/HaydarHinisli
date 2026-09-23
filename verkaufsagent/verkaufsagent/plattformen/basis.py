"""Allgemeiner Marktplatz-Adapter.

Füllt das Angebotsformular einer beliebigen Plattform anhand ihrer
Definition (Adressen + Felder + Selektoren) aus, ändert Preise und liest –
soweit angelernt – Aufrufe/Favoriten.
"""
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import BrowserContext, Locator, Page, Playwright

from ..konfiguration import Konfiguration
from ..modelle import Inserat, Produkt, Texte
from ..plattformdef import Definition, Feld

log = logging.getLogger(__name__)

# Eingebaute Wertquellen; alle anderen Feldnamen kommen aus produkt.<plattform>.felder
_PRODUKT_ATTRIBUTE = ("marke", "groesse", "farbe", "material")
_JA = {"ja", "true", "1", "x", "yes"}


class PlattformFehler(RuntimeError):
    pass


class NichtAngemeldet(PlattformFehler):
    pass


class NichtEingerichtet(PlattformFehler):
    pass


class Abgebrochen(PlattformFehler):
    pass


@dataclass
class Veroeffentlicht:
    anzeige_id: str | None
    url: str


@dataclass
class Statistik:
    aufrufe: int | None = None
    favoriten: int | None = None
    nachrichten: int | None = None
    aktiv: bool = True  # False = gelöscht/verkauft/nicht mehr auffindbar


def preis_text(preis: float) -> str:
    return str(int(preis)) if float(preis).is_integer() else f"{preis:.2f}".replace(".", ",")


def _zahl(text: str | None) -> int | None:
    ziffern = re.sub(r"\D", "", text or "")
    return int(ziffern) if ziffern else None


class Marktplatz:
    def __init__(self, pw: Playwright, konf: Konfiguration, definition: Definition, sichtbar: bool = False):
        self.konf = konf
        self.d = definition
        self.name = definition.name
        profil = konf.datenordner / "browser" / definition.name
        profil.mkdir(parents=True, exist_ok=True)
        self.ctx: BrowserContext = pw.chromium.launch_persistent_context(
            user_data_dir=str(profil),
            headless=konf.browser.headless and not sichtbar,
            slow_mo=konf.browser.langsam_ms,
            locale="de-DE",
            timezone_id="Europe/Berlin",
            viewport={"width": 1366, "height": 900},
            executable_path=konf.browser.programm or os.environ.get("VERKAUFSAGENT_BROWSER") or None,
        )
        self.ctx.set_default_timeout(konf.browser.timeout_ms)
        self.page: Page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

    def schliessen(self) -> None:
        self.ctx.close()

    # ---- Hilfen -----------------------------------------------------------

    def finde(self, selektoren: list[str], was: str, timeout_ms: int | None = None, sichtbar: bool = True) -> Locator:
        if not selektoren:
            raise NichtEingerichtet(f"{self.d.anzeigename}: '{was}' ist nicht angelernt – 'einrichten {self.name}' ausführen")
        frist = time.monotonic() + (timeout_ms or self.konf.browser.timeout_ms) / 1000
        while True:
            for sel in selektoren:
                loc = self.page.locator(sel).first
                try:
                    if loc.count() and (not sichtbar or loc.is_visible()):
                        return loc
                except Exception:
                    pass
            if time.monotonic() > frist:
                raise PlattformFehler(f"{self.d.anzeigename}: Feld '{was}' nicht gefunden (Selektoren: {selektoren})")
            self.page.wait_for_timeout(300)

    def _abgemeldet(self) -> bool:
        pfad = urlsplit(self.page.url).path.lower() + "?" + urlsplit(self.page.url).query.lower()
        return any(m in pfad for m in self.d.nicht_angemeldet_wenn)

    def screenshot(self, name: str) -> Path:
        ordner = self.konf.datenordner / "screenshots"
        ordner.mkdir(parents=True, exist_ok=True)
        pfad = ordner / f"{datetime.now():%Y%m%d-%H%M%S}-{self.name}-{name}.png"
        try:
            self.page.screenshot(path=str(pfad), full_page=True)
        except Exception as e:  # Screenshot darf nie den eigentlichen Fehler verdecken
            log.debug("Screenshot fehlgeschlagen: %s", e)
        return pfad

    def bestaetigen_oder_abbrechen(self, produkt: Produkt) -> None:
        """Bei auto_veroeffentlichen=false: Formular prüfen lassen, bevor abgeschickt wird."""
        if self.konf.auto_veroeffentlichen:
            return
        bild = self.screenshot(f"{produkt.id}-vorschau")
        antwort = input(f"\n[{self.d.anzeigename}] Formular für '{produkt.name}' ist ausgefüllt (Vorschau: {bild}).\n"
                        "Enter = veröffentlichen, n = abbrechen: ").strip().lower()
        if antwort in ("n", "nein"):
            raise Abgebrochen("vom Nutzer abgebrochen")

    # ---- Anmeldung --------------------------------------------------------

    def ist_angemeldet(self) -> bool:
        self.page.goto(self.d.neu_url or self.d.basis_url)
        self.page.wait_for_load_state("domcontentloaded")
        return not self._abgemeldet()

    def anmelden_interaktiv(self) -> None:
        self.page.goto(self.d.login_url or self.d.basis_url)
        input(f"\nBitte im geöffneten Browser bei {self.d.anzeigename} anmelden (inkl. evtl. Captcha/2FA).\n"
              "Danach hier Enter drücken … ")
        if self.d.neu_url and not self.ist_angemeldet():
            raise NichtAngemeldet("Anmeldung nicht erkannt – bitte erneut versuchen.")

    # ---- Formular ---------------------------------------------------------

    def _wert(self, name: str, produkt: Produkt, texte: Texte, preis: float):
        optionen = produkt.optionen_fuer(self.name)
        if name == "titel":
            return texte.titel
        if name == "beschreibung":
            return texte.beschreibung
        if name == "preis":
            return preis_text(preis)
        if name == "fotos":
            return [str(f) for f in produkt.fotos[:20]]
        if name == "kategorie":
            return optionen.kategorie or None
        if name == "zustand":
            return produkt.zustand.text
        if name in optionen.felder:
            return optionen.felder[name]
        if name in _PRODUKT_ATTRIBUTE:
            return getattr(produkt, name)
        return None

    def _sichtbarer_text(self, text: str, innerhalb: Locator | None = None) -> Locator:
        basis = innerhalb if innerhalb is not None else self.page
        return basis.get_by_text(text, exact=True).locator("visible=true").first

    def _fuellen(self, name: str, feld: Feld, wert) -> None:
        loc = self.finde(feld.selektor, feld.beschriftung or name, sichtbar=feld.typ != "datei")
        if feld.typ == "text":
            loc.fill(str(wert))
        elif feld.typ == "datei":
            loc.set_input_files(wert)
            self.page.wait_for_timeout(1500 + 1000 * min(len(wert), 20))
        elif feld.typ == "auswahl":
            pfad = [str(w) for w in (wert if isinstance(wert, list) else [wert])]
            if (loc.evaluate("e => e.tagName") or "").lower() == "select":
                try:
                    loc.select_option(label=pfad[-1], timeout=3000)
                except Exception:
                    loc.select_option(value=pfad[-1], timeout=3000)
                return
            loc.click()
            for ebene in pfad:
                self._sichtbarer_text(ebene).click(timeout=5000)
                self.page.wait_for_timeout(400)
        elif feld.typ == "klick":
            ziel = self._sichtbarer_text(str(wert), loc)
            (ziel if ziel.count() else self._sichtbarer_text(str(wert))).click(timeout=5000)
        elif feld.typ == "haken":
            loc.check() if str(wert).strip().lower() in _JA else loc.uncheck()

    def veroeffentliche(self, produkt: Produkt, texte: Texte, preis: float) -> Veroeffentlicht:
        if not self.d.eingerichtet:
            raise NichtEingerichtet(f"{self.d.anzeigename} ist noch nicht eingerichtet (fehlt: {', '.join(self.d.fehlend())}) "
                                    f"– 'python -m verkaufsagent einrichten {self.name}' ausführen")
        self.page.goto(self.d.neu_url)
        if self._abgemeldet():
            raise NichtAngemeldet(f"Nicht bei {self.d.anzeigename} angemeldet – 'anmelden {self.name}' ausführen")

        for name, feld in self.d.felder.items():
            wert = self._wert(name, produkt, texte, preis)
            if wert in (None, "", []):
                if feld.pflicht:
                    raise PlattformFehler(f"Pflichtfeld '{feld.beschriftung or name}' hat keinen Wert – "
                                          f"bitte in produkte.yaml unter '{self.name}' angeben")
                continue
            try:
                self._fuellen(name, feld, wert)
            except PlattformFehler:
                if feld.pflicht:
                    raise
                log.warning("%s: optionales Feld '%s' nicht gesetzt", self.d.anzeigename, name)
            except Exception as e:
                if feld.pflicht:
                    raise PlattformFehler(f"Feld '{feld.beschriftung or name}' ({wert!r}) nicht ausfüllbar: {e}") from e
                log.warning("%s: optionales Feld '%s' nicht gesetzt: %s", self.d.anzeigename, name, e)
                self.page.keyboard.press("Escape")

        self.bestaetigen_oder_abbrechen(produkt)
        vorher = self.page.url
        self.finde(self.d.absenden, "Absenden-Knopf").click()
        try:
            self.page.wait_for_url(lambda u: u != vorher, timeout=60000)
        except Exception:
            raise PlattformFehler("Nach dem Absenden hat sich die Seite nicht geändert – evtl. fehlt ein Pflichtfeld "
                                  "(siehe Screenshot)")
        anzeige_id = self._warte_auf_nummer()
        if anzeige_id is None:
            log.warning("%s: Angebots-Nummer nicht aus %s lesbar – Preisänderungen für dieses Angebot nicht möglich",
                        self.d.anzeigename, self.page.url)
        url = self.d.anzeige_url.format(id=anzeige_id) if anzeige_id and self.d.anzeige_url else self.page.url
        return Veroeffentlicht(anzeige_id, url)

    def _warte_auf_nummer(self, sekunden: float = 15) -> str | None:
        """Viele Seiten leiten nach dem Speichern über Zwischenseiten weiter – bis zur Angebots-Nummer warten."""
        frist = time.monotonic() + sekunden
        while True:
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            anzeige_id = self.d.anzeige_id(self.page.url)
            if anzeige_id or time.monotonic() > frist:
                return anzeige_id
            self.page.wait_for_timeout(500)

    def aendere_preis(self, inserat: Inserat, preis: float) -> None:
        if not (self.d.bearbeiten_url and inserat.anzeige_id):
            raise NichtEingerichtet(f"{self.d.anzeigename}: Preisänderung nicht möglich (Bearbeiten-Seite nicht angelernt "
                                    "oder Angebots-Nummer unbekannt)")
        self.page.goto(self.d.bearbeiten_url.format(id=inserat.anzeige_id))
        if self._abgemeldet():
            raise NichtAngemeldet(f"Nicht bei {self.d.anzeigename} angemeldet")
        feld = self.d.felder.get("preis")
        self.finde(self.d.bearbeiten_preis or (feld.selektor if feld else []), "Preis").fill(preis_text(preis))
        vorher = self.page.url
        self.finde(self.d.bearbeiten_absenden or self.d.absenden, "Speichern-Knopf").click()
        try:
            self.page.wait_for_url(lambda u: u != vorher, timeout=30000)
        except Exception:
            self.page.wait_for_load_state("networkidle")

    def lese_statistik(self, inserat: Inserat) -> Statistik:
        stat = Statistik()
        if not (self.d.anzeige_url and inserat.anzeige_id):
            return stat
        antwort = self.page.goto(self.d.anzeige_url.format(id=inserat.anzeige_id))
        if antwort is not None and antwort.status in (404, 410):
            stat.aktiv = False
            return stat
        if self.d.verkauft_texte:
            inhalt = self.page.locator("body").inner_text().lower()
            if any(t.lower() in inhalt for t in self.d.verkauft_texte):
                stat.aktiv = False
                return stat
        for attr in ("aufrufe", "favoriten"):
            sel = getattr(self.d, attr)
            if sel:
                try:
                    setattr(stat, attr, _zahl(self.finde(sel, attr, 5000, sichtbar=False).inner_text()))
                except PlattformFehler:
                    log.debug("%s: %s nicht lesbar", self.d.anzeigename, attr)
        return stat
