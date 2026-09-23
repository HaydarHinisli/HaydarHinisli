"""Gemeinsame Browser-Logik für alle Plattformen."""
from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml
from playwright.sync_api import BrowserContext, Locator, Page, Playwright, TimeoutError as PwTimeout

from ..konfiguration import Konfiguration
from ..modelle import Inserat, Plattform, Produkt, Texte

log = logging.getLogger(__name__)

_SELEKTOR_DATEI = Path(__file__).resolve().parent.parent / "selektoren.yaml"


class PlattformFehler(RuntimeError):
    pass


class NichtAngemeldet(PlattformFehler):
    pass


class Abgebrochen(PlattformFehler):
    pass


@dataclass
class Veroeffentlicht:
    anzeige_id: str
    url: str


@dataclass
class Statistik:
    aufrufe: int | None = None
    favoriten: int | None = None
    nachrichten: int | None = None
    aktiv: bool = True  # False = gelöscht/verkauft/nicht mehr auffindbar


def lade_selektoren(plattform: Plattform, extra: Path | None = None) -> dict[str, list[str]]:
    daten = yaml.safe_load(_SELEKTOR_DATEI.read_text(encoding="utf-8"))[plattform.value]
    if extra and extra.exists():
        daten.update((yaml.safe_load(extra.read_text(encoding="utf-8")) or {}).get(plattform.value, {}))
    return daten


class PlattformBasis(ABC):
    plattform: Plattform
    startseite: str

    def __init__(self, pw: Playwright, konf: Konfiguration, sichtbar: bool = False):
        self.konf = konf
        self.sel = lade_selektoren(self.plattform, konf.datenordner / "selektoren.yaml")
        profil = konf.datenordner / "browser" / self.plattform.value
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

    def _locator(self, alternative: str) -> Locator:
        art, _, wert = alternative.partition(":")
        if art == "label" and wert:
            return self.page.get_by_label(wert, exact=False)
        if art == "text" and wert:
            return self.page.get_by_text(wert, exact=True)
        if art == "button" and wert:
            return self.page.get_by_role("button", name=wert)
        if art == "placeholder" and wert:
            return self.page.get_by_placeholder(wert)
        return self.page.locator(alternative)

    def finde(self, schluessel: str, timeout_ms: int | None = None, sichtbar: bool = True) -> Locator:
        frist = time.monotonic() + (timeout_ms or self.konf.browser.timeout_ms) / 1000
        alternativen = self.sel[schluessel]
        while True:
            for alt in alternativen:
                loc = self._locator(alt).first
                try:
                    if loc.count() and (not sichtbar or loc.is_visible()):
                        return loc
                except PwTimeout:
                    pass
            if time.monotonic() > frist:
                raise PlattformFehler(f"Element nicht gefunden: {self.plattform.value}.{schluessel} (Selektoren: {alternativen})")
            self.page.wait_for_timeout(300)

    def optional(self, schluessel: str, timeout_ms: int = 3000, sichtbar: bool = True) -> Locator | None:
        try:
            return self.finde(schluessel, timeout_ms, sichtbar)
        except PlattformFehler:
            return None

    def hole_json(self, url: str) -> tuple[int, dict | None]:
        """Lädt eine JSON-Adresse im angemeldeten Browser (nutzt dessen Cookies)."""
        antwort = self.page.goto(url)
        if antwort is None:
            return 0, None
        if not antwort.ok:
            return antwort.status, None
        try:
            return antwort.status, antwort.json()
        except Exception:
            return antwort.status, None

    def cookies_akzeptieren(self) -> None:
        knopf = self.optional("cookie_akzeptieren", 4000)
        if knopf:
            knopf.click()

    def screenshot(self, name: str) -> Path:
        ordner = self.konf.datenordner / "screenshots"
        ordner.mkdir(parents=True, exist_ok=True)
        pfad = ordner / f"{datetime.now():%Y%m%d-%H%M%S}-{self.plattform.value}-{name}.png"
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
        antwort = input(f"\n[{self.plattform.value}] Formular für '{produkt.name}' ist ausgefüllt (Vorschau: {bild}).\n"
                        "Enter = veröffentlichen, n = abbrechen: ").strip().lower()
        if antwort in ("n", "nein"):
            raise Abgebrochen("vom Nutzer abgebrochen")

    # ---- Anmeldung --------------------------------------------------------

    def anmelden_interaktiv(self) -> None:
        self.page.goto(self.startseite)
        self.cookies_akzeptieren()
        input(f"\nBitte im geöffneten Browser bei {self.plattform.value} anmelden (inkl. evtl. Captcha/2FA).\n"
              "Danach hier Enter drücken … ")
        if not self.ist_angemeldet():
            raise NichtAngemeldet("Anmeldung nicht erkannt – bitte erneut versuchen.")

    # ---- Plattformspezifisch ---------------------------------------------

    @abstractmethod
    def ist_angemeldet(self) -> bool: ...

    @abstractmethod
    def veroeffentliche(self, produkt: Produkt, texte: Texte, preis: float) -> Veroeffentlicht: ...

    @abstractmethod
    def aendere_preis(self, inserat: Inserat, preis: float) -> None: ...

    @abstractmethod
    def lese_statistik(self, inserat: Inserat) -> Statistik: ...


def preis_text(preis: float) -> str:
    return str(int(preis)) if float(preis).is_integer() else f"{preis:.2f}".replace(".", ",")
