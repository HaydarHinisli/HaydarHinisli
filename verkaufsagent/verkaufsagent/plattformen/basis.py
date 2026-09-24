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
from ..zugang import lade_zugang

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
    preis: float | None = None  # tatsächlich gesetzter Preis (bei Preis-Menüs evtl. gerundet)


@dataclass
class Statistik:
    aufrufe: int | None = None
    favoriten: int | None = None
    nachrichten: int | None = None
    aktiv: bool = True  # False = gelöscht/verkauft/nicht mehr auffindbar


def preis_text(preis: float) -> str:
    return str(int(preis)) if float(preis).is_integer() else f"{preis:.2f}".replace(".", ",")


def _betrag(text: str) -> float | None:
    """Liest einen Geldbetrag aus Menütext wie '$ 24.99', '25 €' oder '1.000,50'."""
    treffer = re.search(r"\d[\d.,]*", text or "")
    if not treffer:
        return None
    zahl = treffer.group(0).rstrip(".,")
    if "," in zahl and "." in zahl:
        zahl = zahl.replace(".", "").replace(",", ".") if zahl.rfind(",") > zahl.rfind(".") else zahl.replace(",", "")
    elif "," in zahl:
        zahl = zahl.replace(",", ".") if len(zahl.split(",")[-1]) <= 2 else zahl.replace(",", "")
    try:
        return float(zahl)
    except ValueError:
        return None


def waehle_preisstufe(stufen: list[float], ziel: float, minimum: float) -> float | None:
    """Wählt aus festen Preisstufen: exakt, sonst die höchste Stufe <= Ziel (aber >= Minimum).
    Gibt es keine, None – der Preis wird dann nie unter die Untergrenze oder über das Ziel gesetzt."""
    passend = [s for s in stufen if minimum - 1e-9 <= s <= ziel + 1e-9]
    return max(passend) if passend else None


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
        self._cookie_datei = konf.datenordner / "browser" / f"{definition.name}-cookies.json"
        self._cookies_laden()

    # Manche Seiten (z. B. panty.com) halten die Anmeldung nur in Sitzungs-Cookies, die der
    # Browser beim Schließen verwirft. Daher alle Cookies sichern und beim Start wieder setzen.
    def _cookies_laden(self) -> None:
        try:
            if self._cookie_datei.exists():
                import json
                jetzt = time.time()
                cookies = [c for c in json.loads(self._cookie_datei.read_text(encoding="utf-8"))
                           if c.get("expires", -1) in (-1, None) or c["expires"] > jetzt]
                if cookies:
                    self.ctx.add_cookies(cookies)
        except Exception as e:
            log.debug("Cookies nicht geladen: %s", e)

    def _cookies_sichern(self) -> None:
        try:
            import json
            self._cookie_datei.write_text(json.dumps(self.ctx.cookies()), encoding="utf-8")
            os.chmod(self._cookie_datei, 0o600)
        except Exception as e:
            log.debug("Cookies nicht gesichert: %s", e)

    def schliessen(self) -> None:
        self._cookies_sichern()
        self.ctx.close()

    # ---- Hilfen -----------------------------------------------------------

    def finde(self, selektoren: list[str], was: str, timeout_ms: int | None = None, sichtbar: bool = True) -> Locator:
        if not selektoren:
            raise NichtEingerichtet(f"{self.d.anzeigename}: '{was}' ist nicht angelernt – 'einrichten {self.name}' ausführen")
        frist = time.monotonic() + (timeout_ms or self.konf.browser.timeout_ms) / 1000
        while True:
            for sel in selektoren:
                # bei mehreren Treffern das erste SICHTBARE Element (versteckte Doppelgänger überspringen)
                loc = (self.page.locator(sel).locator("visible=true") if sichtbar else self.page.locator(sel)).first
                try:
                    if loc.count():
                        return loc
                except Exception:
                    pass
            if time.monotonic() > frist:
                raise PlattformFehler(f"{self.d.anzeigename}: Feld '{was}' nicht gefunden (Selektoren: {selektoren})")
            self.page.wait_for_timeout(300)

    def _abgemeldet(self) -> bool:
        pfad = urlsplit(self.page.url).path.lower() + "?" + urlsplit(self.page.url).query.lower()
        if any(m in pfad for m in self.d.nicht_angemeldet_wenn):
            # Auf der Login-Adresse nach erfolgreicher Anmeldung (kein Passwortfeld mehr) nicht als abgemeldet werten
            if not (getattr(self, "_angemeldet", False) and self.d.login_passwort and not any(
                    self.page.locator(sel).locator("visible=true").count() for sel in self.d.login_passwort)):
                return True
        for sel in self.d.abgemeldet_zeichen:
            try:
                if self.page.locator(sel).first.is_visible():
                    return True
            except Exception:
                pass
        return False

    def anmelden_automatisch(self) -> bool:
        """Meldet sich mit den gespeicherten Zugangsdaten an. True = danach angemeldet."""
        zugang = lade_zugang(self.konf.datenordner, self.name)
        if not (self.d.login_eingerichtet and zugang):
            return False
        log.info("%s: nicht angemeldet – melde mich automatisch an", self.d.anzeigename)
        if self.d.login_url and not self.d.login_klicks:
            self.page.goto(self.d.login_url)
        for nr, schritt in enumerate(self.d.login_klicks, 1):
            self._klick_schritt(schritt, f"Weg zum Login, Klick {nr}", 10000)
            self.page.wait_for_timeout(800)
        self.finde(self.d.login_benutzer, "Login: Benutzername/E-Mail").fill(zugang[0])
        self.finde(self.d.login_passwort, "Login: Passwort").fill(zugang[1])
        if self.d.login_merken:  # „Remember me“ – sonst verfällt die Anmeldung beim Schließen des Browsers
            try:
                kaestchen = self.finde(self.d.login_merken, "Remember me", 3000, sichtbar=False)
                if kaestchen.evaluate("e => e.type === 'checkbox'"):
                    if not kaestchen.is_checked():
                        kaestchen.check(force=True)
                else:
                    kaestchen.click()
            except Exception as e:
                log.debug("„Remember me“ nicht gesetzt: %s", e)
        self.finde(self.d.login_absenden, "Login-Knopf").click()
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        self.page.wait_for_timeout(2500)
        # Erfolg = das Passwortfeld ist verschwunden (die Adresse kann danach trotzdem noch „login“ enthalten)
        passwort_noch_da = any(self.page.locator(sel).locator("visible=true").count() for sel in self.d.login_passwort)
        if passwort_noch_da or any(self.page.locator(sel).locator("visible=true").count() for sel in self.d.abgemeldet_zeichen):
            bild = self.screenshot("login-fehlgeschlagen")
            log.warning("%s: Anmeldung fehlgeschlagen (Screenshot: %s)", self.d.anzeigename, bild)
            return False
        self._angemeldet = True
        self._cookies_sichern()
        return True

    def sicherstellen_angemeldet(self) -> None:
        if self._abgemeldet() and not self.anmelden_automatisch():
            hinweis = ("Automatische Anmeldung fehlgeschlagen – Zugangsdaten prüfen ('login " + self.name + "')"
                       if self.d.login_eingerichtet else
                       f"'anmelden {self.name}' ausführen oder automatische Anmeldung einrichten ('login {self.name}')")
            raise NichtAngemeldet(f"Nicht bei {self.d.anzeigename} angemeldet – {hinweis}")

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
            return preis
        if name == "fotos":
            return [str(f) for f in produkt.fotos[:20]]
        if name == "kategorie":
            return optionen.kategorie or None
        if name == "zustand":
            return produkt.zustand.text
        if name in optionen.felder:
            return optionen.felder[name]
        if name in _PRODUKT_ATTRIBUTE and getattr(produkt, name):
            return getattr(produkt, name)
        return self.d.standardwerte.get(name)

    def _sichtbarer_text(self, text: str, innerhalb: Locator | None = None) -> Locator:
        basis = innerhalb if innerhalb is not None else self.page
        return basis.get_by_text(text, exact=True).locator("visible=true").first

    @staticmethod
    def _ist_select(loc: Locator) -> bool:
        return (loc.evaluate("e => e.tagName") or "").lower() == "select"

    def _menue(self, loc: Locator) -> Locator | None:
        """Findet das echte <select> zu einem Feld. Viele Seiten zeigen ein gestaltetes Textfeld
        („Select price“) und verstecken das eigentliche Menü direkt daneben."""
        if self._ist_select(loc):
            return loc
        try:
            if loc.is_editable():
                return None  # normales Eingabefeld – kein gestaltetes Menü
        except Exception:
            pass
        for ebene in (1, 2, 3):  # von innen nach außen: das nächstgelegene Menü gehört zum Feld
            daneben = loc.locator(f"xpath=ancestor::*[{ebene}]//select")
            try:
                anzahl = daneben.count()
            except Exception:
                return None
            if anzahl == 1:
                versteckt = daneben.first.evaluate(
                    "e => { const s = getComputedStyle(e), r = e.getBoundingClientRect();"
                    " return s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) === 0"
                    " || r.width < 2 || r.height < 2 }")
                return daneben.first if versteckt else None  # nur das versteckte Menü dahinter
            if anzahl > 1:
                return None  # mehrdeutig – lieber gar nicht als das falsche Menü
        return None

    @staticmethod
    def _anzeige_setzen(loc: Locator, menue: Locator) -> None:
        """Gestaltetes Textfeld an die Auswahl im versteckten Menü angleichen (nur Optik)."""
        if loc == menue:
            return
        try:
            text = menue.evaluate("e => e.options[e.selectedIndex] ? e.options[e.selectedIndex].textContent.trim() : ''")
            loc.evaluate("(e, t) => { if (e.tagName === 'INPUT') e.value = t }", text)
        except Exception:
            pass

    @staticmethod
    def _option_waehlen(loc: Locator, wert: str) -> None:
        """Wählt in einem <select> die passende Option: exakt, dann Anfang ('M' -> 'Medium'), dann enthalten."""
        optionen = loc.evaluate("e => Array.from(e.options).map(o => [o.value, o.textContent.trim()])")
        w = wert.strip().lower()
        for pruefung in (lambda t: t == w, lambda t: t.startswith(w), lambda t: len(w) >= 3 and w in t):
            for value, text in optionen:
                if pruefung(text.lower()) or pruefung(value.lower()):
                    loc.select_option(value=value, force=True)
                    return
        raise PlattformFehler(f"Option '{wert}' nicht im Menü (verfügbar: {', '.join(t for _, t in optionen if t)})")

    def preis_setzen(self, loc: Locator, preis: float, minimum: float) -> float:
        """Setzt den Preis – als Text oder durch Wahl einer festen Preisstufe. Gibt den gesetzten Preis zurück."""
        menue = self._menue(loc)
        if menue is None:
            try:
                beschreibbar = loc.is_editable()
            except Exception:
                beschreibbar = True
            if beschreibbar:
                loc.fill(preis_text(preis))
                return preis
            return self._preis_per_klickliste(loc, preis, minimum)
        anzeige, loc = loc, menue
        optionen = loc.evaluate("e => Array.from(e.options).map(o => [o.value, o.textContent.trim()])")
        stufen = {}
        for value, text in optionen:
            betrag = _betrag(text) if _betrag(text) is not None else _betrag(value)
            if betrag is not None and betrag > 0:
                stufen.setdefault(betrag, value)
        gewaehlt = waehle_preisstufe(list(stufen), preis, minimum)
        if gewaehlt is None:
            raise PlattformFehler(f"Keine Preisstufe zwischen {minimum:.2f} und {preis:.2f} im Menü "
                                  f"(verfügbar: {', '.join(f'{s:g}' for s in sorted(stufen)) or '-'})")
        loc.select_option(value=stufen[gewaehlt], force=True)
        self._anzeige_setzen(anzeige, loc)
        if gewaehlt != preis:
            log.info("%s: Preis %.2f als Stufe %.2f gesetzt (feste Preisstufen)", self.d.anzeigename, preis, gewaehlt)
        return gewaehlt

    def _preis_per_klickliste(self, loc: Locator, preis: float, minimum: float) -> float:
        """Gestaltetes Preis-Menü ohne echtes <select>: aufklicken, sichtbare Stufen lesen, passende anklicken."""
        loc.click()
        self.page.wait_for_timeout(500)
        eintraege = self.page.locator("li:visible, [role=option]:visible")
        texte = [t.strip() for t in eintraege.all_inner_texts()]
        stufen = {b: t for t in texte if (b := _betrag(t)) is not None and b > 0}
        gewaehlt = waehle_preisstufe(list(stufen), preis, minimum)
        if gewaehlt is None:
            self.page.keyboard.press("Escape")
            raise PlattformFehler(f"Keine Preisstufe zwischen {minimum:.2f} und {preis:.2f} im Menü "
                                  f"(verfügbar: {', '.join(f'{s:g}' for s in sorted(stufen)) or '-'})")
        self._sichtbarer_text(stufen[gewaehlt]).click(timeout=5000)
        return gewaehlt

    def _fuellen(self, name: str, feld: Feld, wert, minimum: float = 0) -> float | None:
        loc = self.finde(feld.selektor, feld.beschriftung or name, sichtbar=feld.typ != "datei")
        if name == "preis":
            return self.preis_setzen(loc, float(wert), minimum)
        if feld.typ == "text":
            loc.fill(str(wert))
        elif feld.typ == "datei":
            loc.set_input_files(wert)
            self.page.wait_for_timeout(1500 + 1000 * min(len(wert), 20))
        elif feld.typ == "auswahl":
            pfad = [str(w) for w in (wert if isinstance(wert, list) else [wert])]
            menue = self._menue(loc)
            if menue is not None:
                self._option_waehlen(menue, pfad[-1])
                self._anzeige_setzen(loc, menue)
                return None
            loc.click()
            for ebene in pfad:
                self._sichtbarer_text(ebene).click(timeout=5000)
                self.page.wait_for_timeout(400)
        elif feld.typ == "klick":
            ziel = self._sichtbarer_text(str(wert), loc)
            (ziel if ziel.count() else self._sichtbarer_text(str(wert))).click(timeout=5000)
        elif feld.typ == "haken":
            loc.check() if str(wert).strip().lower() in _JA else loc.uncheck()
        return None

    def veroeffentliche(self, produkt: Produkt, texte: Texte, preis: float) -> Veroeffentlicht:
        if not self.d.eingerichtet:
            raise NichtEingerichtet(f"{self.d.anzeigename} ist noch nicht eingerichtet (fehlt: {', '.join(self.d.fehlend())}) "
                                    f"– 'python -m verkaufsagent einrichten {self.name}' ausführen")
        # Manche Seiten (z. B. panty.com) melden ab, wenn man sie mitten in der Sitzung neu aufruft.
        # Mit angelerntem Klickweg daher nur beim ersten Mal laden, danach per Klick (Logo …) navigieren.
        auf_der_seite = urlsplit(self.page.url).netloc == urlsplit(self.d.neu_url).netloc
        if not (self.d.navigation and auf_der_seite):
            self.page.goto(self.d.neu_url)
        self.sicherstellen_angemeldet()
        try:
            self._zum_formular()
        except PlattformFehler:
            # Häufigster Grund: unterwegs abgemeldet (z. B. „My Offers“ fehlt) – anmelden und neu versuchen
            if not self.anmelden_automatisch():
                raise
            self.page.goto(self.d.neu_url)
            self._zum_formular()

        gesetzter_preis = preis
        for name, feld in self.d.felder.items():
            wert = self._wert(name, produkt, texte, preis)
            if wert in (None, "", []):
                if feld.pflicht:
                    raise PlattformFehler(f"Pflichtfeld '{feld.beschriftung or name}' hat keinen Wert – "
                                          f"bitte in produkte.yaml unter '{self.name}' angeben")
                continue
            try:
                ergebnis = self._fuellen(name, feld, wert, minimum=produkt.untergrenze())
                if name == "preis" and ergebnis is not None:
                    gesetzter_preis = ergebnis
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
        return Veroeffentlicht(anzeige_id, url, gesetzter_preis)

    def _zum_formular(self) -> None:
        for nr, schritt in enumerate(self.d.navigation, 1):
            try:
                self._klick_schritt(schritt, f"Weg zum Formular, Klick {nr}", 5000 if nr == 1 else 10000)
            except PlattformFehler:
                if nr > 1 or self.page.url == self.d.neu_url:
                    raise
                self.page.goto(self.d.neu_url)  # Logo nicht gefunden – doch neu laden
                self._klick_schritt(schritt, f"Weg zum Formular, Klick {nr}", 10000)
            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            self.page.wait_for_timeout(800)

    def _klick_schritt(self, selektoren: list[str], was: str, timeout_ms: int) -> None:
        """Klickt einen Schritt eines Klickwegs. Steckt der Link in einem zugeklappten Menü
        (z. B. „My Offers“ unter dem Konto-Symbol), wird er direkt ausgelöst."""
        try:
            self.finde(selektoren, was, timeout_ms).click()
            return
        except PlattformFehler:
            pass
        try:
            versteckt = self.finde(selektoren, was, 2000, sichtbar=False)
        except PlattformFehler:
            raise PlattformFehler(f"{self.d.anzeigename}: '{was}' nicht gefunden (Selektoren: {selektoren}). "
                                  "Bist du im Agent-Browser angemeldet?") from None
        log.info("%s: '%s' liegt in einem zugeklappten Menü – löse den Link direkt aus", self.d.anzeigename, was)
        versteckt.evaluate("e => e.click()")

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

    def aendere_preis(self, inserat: Inserat, preis: float, minimum: float = 0) -> float:
        """Setzt einen neuen Preis und gibt den tatsächlich gesetzten zurück."""
        if not (self.d.bearbeiten_url and inserat.anzeige_id):
            raise NichtEingerichtet(f"{self.d.anzeigename}: Preisänderung nicht möglich (Bearbeiten-Seite nicht angelernt "
                                    "oder Angebots-Nummer unbekannt)")
        self.page.goto(self.d.bearbeiten_url.format(id=inserat.anzeige_id))
        self.sicherstellen_angemeldet()
        feld = self.d.felder.get("preis")
        loc = self.finde(self.d.bearbeiten_preis or (feld.selektor if feld else []), "Preis")
        gesetzt = self.preis_setzen(loc, preis, minimum)
        if inserat.preis_aktuell is not None and gesetzt >= inserat.preis_aktuell:
            return gesetzt  # keine niedrigere Stufe möglich – nichts speichern
        vorher = self.page.url
        self.finde(self.d.bearbeiten_absenden or self.d.absenden, "Speichern-Knopf").click()
        try:
            self.page.wait_for_url(lambda u: u != vorher, timeout=30000)
        except Exception:
            self.page.wait_for_load_state("networkidle")
        return gesetzt

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
