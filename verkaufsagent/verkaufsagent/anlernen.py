"""Einrichtungs-Assistent: lernt das Angebotsformular einer Plattform im Browser an.

Der Nutzer klickt im echten Formular nacheinander auf die Felder, die der
Assistent nennt. Ein kleines Skript im Browser fängt diese Klicks ab (es wird
nichts ausgelöst oder abgeschickt) und ermittelt robuste Selektoren.
"""
from __future__ import annotations

import logging
import re
from typing import Callable
from urllib.parse import urlsplit

from .plattformdef import Definition, Feld, Register
from .plattformen.basis import Marktplatz

log = logging.getLogger(__name__)

REKORDER = r"""
(() => {
  if (window.__va) return;
  window.__va = {aktiv: false, auswahl: null, element: null};
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
  const zufaellig = (s) => /\d{3,}|[a-f0-9]{8,}|^:r|^mui-|^react-/i.test(s);
  function selektoren(el) {
    const tag = el.tagName.toLowerCase(), aus = [];
    if (el.id && !zufaellig(el.id)) aus.push('#' + esc(el.id));
    for (const a of ['data-testid', 'data-test', 'data-qa', 'name', 'aria-label', 'placeholder']) {
      const v = el.getAttribute(a);
      if (v && !zufaellig(v)) aus.push(`${tag}[${a}="${v.replace(/"/g, '\\"')}"]`);
    }
    if (tag === 'button' || tag === 'a' || el.getAttribute('role') === 'button') {
      const t = (el.innerText || '').trim();
      if (t && t.length < 40) aus.push(`${tag}:has-text("${t.replace(/"/g, '\\"')}")`);
    }
    const teile = [];
    for (let e = el; e && e.nodeType === 1 && e !== document.body; e = e.parentElement) {
      if (e.id && !zufaellig(e.id)) { teile.unshift('#' + esc(e.id)); break; }
      let t = e.tagName.toLowerCase();
      const gleiche = e.parentElement ? Array.from(e.parentElement.children).filter(c => c.tagName === e.tagName) : [];
      if (gleiche.length > 1) t += `:nth-of-type(${gleiche.indexOf(e) + 1})`;
      teile.unshift(t);
    }
    aus.push(teile.join(' > '));
    return [...new Set(aus)];
  }
  window.__va.selektoren = selektoren;
  // Anzeigename eines Elements – NIE den Inhalt von Eingabefeldern (Passwörter!)
  const eingabe = (el) => el.matches && el.matches('input:not([type=submit]):not([type=button]),textarea,select,[contenteditable=true]');
  const name = (el) => {
    if (eingabe(el)) {
      if ((el.getAttribute('type') || '').toLowerCase() === 'password') return 'Passwort-Feld';
      return el.getAttribute('placeholder') || el.getAttribute('aria-label') || el.getAttribute('name') || 'Eingabefeld';
    }
    return ((el.matches && el.matches('input') ? el.value : el.innerText) || '').trim().slice(0, 40);
  };
  window.__va.dateifeld = () => {
    for (let e = window.__va.element; e; e = e.parentElement) {
      const f = e.matches && e.matches('input[type=file]') ? e : e.querySelector && e.querySelector('input[type=file]');
      if (f) return selektoren(f);
    }
    const alle = document.querySelectorAll('input[type=file]');
    return alle.length ? selektoren(alle[0]) : [];
  };
  const ziel = (el) => el.closest('input,textarea,select,button,[role=combobox],[role=button],[contenteditable=true]') || el;
  const abfangen = (ev) => {
    if (!window.__va.aktiv) return;
    if (window.__va.durchlassen) {
      // Navigations-Modus: Klick wird ausgeführt, aber gemerkt (übersteht auch einen Seitenwechsel)
      if (ev.type !== 'click') return;
      if (eingabe(ev.target)) {  // Eingabefelder gehören nicht zum Klickweg
        const daten = {eingabefeld: true, text: name(ev.target)};
        window.__va.auswahl = daten;
        try { sessionStorage.setItem('__va_auswahl', JSON.stringify(daten)); } catch (e) {}
        return;
      }
      const el = ev.target.closest('a,button,[role=button],[role=menuitem],input[type=submit],li') || ev.target;
      const daten = {selektoren: selektoren(el), text: name(el)};
      window.__va.auswahl = daten;
      try { sessionStorage.setItem('__va_auswahl', JSON.stringify(daten)); } catch (e) {}
      return;
    }
    ev.preventDefault(); ev.stopPropagation(); ev.stopImmediatePropagation();
    if (ev.type !== 'click') return;
    const el = ziel(ev.target);
    window.__va.element = el;
    window.__va.auswahl = {selektoren: selektoren(el), tag: el.tagName.toLowerCase(), text: name(el)};
    el.style.outline = '3px solid #e91e63';
  };
  for (const typ of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) document.addEventListener(typ, abfangen, true);
})();
"""

HINWEIS = {
    "text": "das Eingabefeld",
    "datei": "den Knopf bzw. Bereich zum Hochladen von Fotos",
    "auswahl": "das Auswahlfeld/Menü",
    "klick": "den Bereich mit den Auswahlmöglichkeiten",
    "haken": "das Kästchen zum Anhaken",
}
TYP_KUERZEL = {"t": "text", "a": "auswahl", "k": "klick", "h": "haken"}

Frage = Callable[[str], str]


class Assistent:
    def __init__(self, marktplatz: Marktplatz, register: Register, frage: Frage = input, ausgabe=print):
        self.m = marktplatz
        self.page = marktplatz.page
        self.register = register
        self.frage = frage
        self.ausgabe = ausgabe
        self.page.context.add_init_script(REKORDER)

    # ---- Aufnahme ---------------------------------------------------------

    def _bereit(self) -> None:
        self.page.wait_for_load_state("domcontentloaded")
        self.page.evaluate(REKORDER)

    def _klick_aufnehmen(self, text: str, datei: bool = False) -> list[str]:
        """Lässt den Nutzer auf ein Element klicken und gibt dessen Selektoren zurück ([] = übersprungen)."""
        self._bereit()
        self.page.evaluate("window.__va.aktiv = true; window.__va.auswahl = null")
        self.frage(text)
        self._bereit()
        auswahl = self.page.evaluate("window.__va.auswahl")
        selektoren = self.page.evaluate("window.__va.dateifeld()") if (auswahl and datei) else (auswahl or {}).get("selektoren", [])
        self.page.evaluate("window.__va.aktiv = false")
        return self._pruefen(selektoren)

    def _pruefen(self, selektoren: list[str]) -> list[str]:
        """Behält nur Selektoren, die auf der Seite etwas finden – eindeutige zuerst."""
        treffer = []
        for sel in selektoren:
            try:
                anzahl = self.page.locator(sel).count()
            except Exception:
                continue
            if anzahl:
                treffer.append((anzahl != 1, sel))
        return [s for _, s in sorted(treffer, key=lambda t: t[0])]

    # ---- Ablauf -----------------------------------------------------------

    def ausfuehren(self) -> Definition:
        d = self.m.d.model_copy(deep=True)
        self.page.goto(d.login_url or d.basis_url)
        self.page.bring_to_front()
        text = (f"\n1) Im Browserfenster, das der Agent gerade geöffnet hat (NICHT in Safari/deinem normalen Browser):\n"
                f"   bei {d.anzeigename} anmelden und das Formular für ein NEUES Angebot öffnen.\n"
                "   Erst wenn das Formular zu sehen ist, hier Enter drücken … ")
        antwort = self.frage(text)
        while not (urlsplit(self.page.url).path.strip("/") or urlsplit(self.page.url).query):
            if antwort.strip().lower().startswith("j"):
                break
            antwort = self.frage(f"   ⚠ Der Browser zeigt die Adresse {self.page.url} (Startseite).\n"
                                 "   Ist das Angebotsformular trotzdem zu sehen? Dann j + Enter.\n"
                                 "   Sonst Formular öffnen und nur Enter … ")
        d.neu_url = self.page.url
        d.navigation = []
        if not (urlsplit(d.neu_url).path.strip("/") or urlsplit(d.neu_url).query):
            self._navigation_aufnehmen(d)
        self.register.speichere(d)  # Zwischenstand – bei Abbruch geht nichts verloren
        self.ausgabe(f"   ✔ Formular-Adresse: {d.neu_url}")

        self.ausgabe("\n2) Jetzt die Felder: Klicke im Browser auf das genannte Feld und drücke dann hier Enter.\n"
                     "   (Klicks werden abgefangen – es wird nichts ausgelöst. Nur Enter ohne Klick = überspringen.)")
        for nr, (name, feld) in enumerate(d.felder.items(), 1):
            text = (f"   [{nr}/{len(d.felder)}] {feld.beschriftung or name}: klicke auf {HINWEIS[feld.typ]}"
                    f"{' (Pflicht)' if feld.pflicht else ''}{' – schon angelernt, Enter = behalten' if feld.selektor else ''} … ")
            sel = self._klick_aufnehmen(text, datei=feld.typ == "datei")
            if sel:
                feld.selektor = sel
                self.register.speichere(d)
                self.ausgabe(f"      ✔ {sel[0]}")
            elif feld.selektor:
                self.ausgabe("      ✔ bereits angelernt – behalten")
            elif feld.pflicht:
                self.ausgabe("      ⚠ übersprungen – dieses Pflichtfeld muss noch angelernt werden")

        while True:
            name = self.frage("\n3) Weiteres Feld anlernen (z. B. tragedauer, versandart)? Namen eingeben oder Enter = fertig: ").strip()
            if not name:
                break
            name = re.sub(r"[^a-z0-9_]", "_", name.lower())
            typ = TYP_KUERZEL.get(self.frage("   Art: [t]ext, [a]uswahl/Menü, [k]lick auf Option, [h]aken: ").strip().lower()[:1], "text")
            pflicht = self.frage("   Pflichtfeld? [j/n]: ").strip().lower().startswith("j")
            sel = self._klick_aufnehmen(f"   Klicke auf {HINWEIS[typ]} für '{name}' … ")
            if sel:
                d.felder[name] = Feld(typ=typ, selektor=sel, pflicht=pflicht, beschriftung=name.replace("_", " ").capitalize())
                self.ausgabe(f"      ✔ {sel[0]}  – Wert pro Produkt in produkte.yaml: {d.name}: {{felder: {{{name}: ...}}}}")

        sel = self._klick_aufnehmen("\n4) Klicke auf den Knopf zum Veröffentlichen/Speichern (wird NICHT ausgelöst) … ")
        if sel:
            d.absenden = sel
            self.register.speichere(d)
            self.ausgabe(f"   ✔ {sel[0]}")
        elif d.absenden:
            self.ausgabe("   ✔ bereits angelernt – behalten")

        self._angebotsseiten(d)
        pfad = self.register.speichere(d)
        self.ausgabe(f"\nGespeichert: {pfad}")
        fehlt = d.fehlend()
        self.ausgabe("✔ Einrichtung vollständig – der Agent kann jetzt inserieren." if not fehlt
                     else f"⚠ Noch nicht vollständig, es fehlt: {', '.join(fehlt)}. 'einrichten {d.name}' erneut ausführen.")
        return d

    def _klickweg(self, ziel: str) -> list[list[str]]:
        """Merkt sich Klicks, die wirklich ausgeführt werden, bis der Nutzer 'f' eingibt."""
        schritte: list[list[str]] = []
        while True:
            self._bereit()
            self.page.evaluate("window.__va.aktiv = true; window.__va.durchlassen = true; window.__va.auswahl = null;"
                               "try { sessionStorage.removeItem('__va_auswahl') } catch (e) {}")
            antwort = self.frage(f"   Schritt {len(schritte) + 1}: im Browser klicken, dann hier Enter "
                                 f"(ist {ziel} zu sehen: f + Enter) … ")
            self._bereit()
            daten = self.page.evaluate(
                "(() => { try { const d = sessionStorage.getItem('__va_auswahl'); if (d) return JSON.parse(d) } catch (e) {}"
                " return window.__va.auswahl })()")
            self.page.evaluate("window.__va.aktiv = false; window.__va.durchlassen = false;"
                               "try { sessionStorage.removeItem('__va_auswahl') } catch (e) {}")
            fertig = antwort.strip().lower().startswith("f")
            if daten and daten.get("eingabefeld"):
                self.ausgabe(f"      ⚠ Das war ein Eingabefeld ({daten.get('text')}) – nicht gemerkt. Ist {ziel} zu sehen, "
                             "zuerst f + Enter; die Felder kommen danach.")
                if not fertig:
                    continue
            elif daten and daten.get("selektoren"):
                schritte.append(daten["selektoren"])
                self.ausgabe(f"      ✔ „{daten.get('text') or daten['selektoren'][0]}“")
            elif not fertig:
                self.ausgabe("      ⚠ kein Klick erkannt – bitte im Agent-Browser klicken")
            if fertig:
                return schritte

    def _navigation_aufnehmen(self, d: Definition) -> None:
        """Für Formulare ohne eigene Adresse: den Klickweg von der Startseite zum Formular merken."""
        self.ausgabe("\n   Das Formular hat keine eigene Adresse – der Agent muss sich jedes Mal durchklicken.\n"
                     "   Klicke jetzt im Agent-Browser den Weg zum Formular – BEGINNE mit dem Logo der Seite\n"
                     "   (oben links, führt zur Startseite), dann z. B. MY OFFERS → + POST OFFER → Used Panties.\n"
                     "   Nach JEDEM Klick hier Enter. Diese Klicks werden ausgeführt.")
        d.navigation = self._klickweg("das Formular")
        self.ausgabe(f"   ✔ Weg zum Formular gemerkt ({len(d.navigation)} Klicks)")

    def login_anlernen(self, passwort_frage=None) -> Definition:
        """Lernt die Anmeldung an und speichert die Zugangsdaten (Mac: im Schlüsselbund)."""
        import getpass

        from .zugang import speichere_zugang

        passwort_frage = passwort_frage or getpass.getpass
        d = self.m.d.model_copy(deep=True)
        self.page.goto(d.login_url or d.basis_url)
        self.page.bring_to_front()
        self.frage(f"\n1) Falls du im Agent-Browser bei {d.anzeigename} angemeldet bist: jetzt ABMELDEN (Logout).\n"
                   "   Wenn du abgemeldet bist, hier Enter … ")
        self.ausgabe("\n2) Klicke jetzt den Weg zum Login-Formular (z. B. auf LOGIN). Nach jedem Klick hier Enter.\n"
                     "   Diese Klicks werden ausgeführt.")
        d.login_klicks = self._klickweg("das Login-Formular")
        if d.login_klicks:
            d.abgemeldet_zeichen = d.login_klicks[0]  # z. B. der LOGIN-Link: sichtbar = abgemeldet
        self.ausgabe("\n3) Jetzt die Felder (Klicks werden abgefangen, es wird nichts abgeschickt):")
        d.login_benutzer = self._klick_aufnehmen("   Klicke auf das Feld für E-Mail bzw. Benutzername … ")
        d.login_passwort = self._klick_aufnehmen("   Klicke auf das Passwort-Feld … ")
        d.login_absenden = self._klick_aufnehmen("   Klicke auf den Anmelden-/Login-Knopf … ")
        if not d.login_eingerichtet:
            self.ausgabe("⚠ Nicht alle Login-Felder erkannt – bitte 'login' noch einmal ausführen.")
            return d
        self.register.speichere(d)

        benutzer = self.frage("\n4) Deine E-Mail bzw. dein Benutzername bei " + d.anzeigename + ": ").strip()
        passwort = passwort_frage("   Dein Passwort (wird beim Tippen nicht angezeigt): ")
        speichere_zugang(self.m.konf.datenordner, d.name, benutzer, passwort)
        self.ausgabe("   ✔ Zugangsdaten gespeichert" + (" (im Mac-Schlüsselbund)" if __import__("sys").platform == "darwin" else ""))

        self.ausgabe("\n5) Test: der Agent meldet sich jetzt selbst an …")
        self.m.d = d
        self.page.goto(d.login_url or d.basis_url)
        if self.m.anmelden_automatisch():
            self.ausgabe("   ✔ Automatische Anmeldung funktioniert.")
        else:
            self.ausgabe("   ⚠ Anmeldung hat nicht geklappt – Zugangsdaten prüfen oder 'login' wiederholen.\n"
                         "     (Bei einem Captcha kann sich der Agent nicht selbst anmelden.)")
        return d

    def _angebotsseiten(self, d: Definition) -> None:
        """Optional: Angebots- und Bearbeiten-Seite – für Statistik und Preisänderungen."""
        self.frage("\n5) Optional (für Preisanpassung & Statistik): Öffne im Browser die ANSICHT eines deiner bestehenden\n"
                   "   Angebote und drücke Enter (oder einfach Enter zum Überspringen) … ")
        anzeige_id = _angebotsnummer(self.page.url) if self.page.url != d.neu_url else None
        if anzeige_id:
            d.anzeige_url = _vorlage_url(self.page.url, anzeige_id)
            d.id_muster = _id_muster(d.anzeige_url)
            self.ausgabe(f"   ✔ Angebotsseite: {d.anzeige_url}")
            for attr, text in (("aufrufe", "die Anzahl der Aufrufe"), ("favoriten", "die Anzahl der Favoriten/Merker")):
                sel = self._klick_aufnehmen(f"   Klicke auf {text} (Enter ohne Klick = gibt es nicht) … ")
                if sel:
                    setattr(d, attr, sel)
                    self.ausgabe(f"      ✔ {sel[0]}")
            woerter = self.frage("   Welcher Text erscheint bei verkauften Angeboten (z. B. 'Verkauft')? Enter = weiß nicht: ").strip()
            if woerter:
                d.verkauft_texte = [w.strip() for w in woerter.split(",") if w.strip()]

        self.frage("\n6) Optional: Öffne die BEARBEITEN-Seite eines bestehenden Angebots und drücke Enter\n"
                   "   (oder einfach Enter zum Überspringen) … ")
        bearbeiten_id = _angebotsnummer(self.page.url) if self.page.url != d.neu_url else None
        if bearbeiten_id:
            d.bearbeiten_url = _vorlage_url(self.page.url, bearbeiten_id)
            self.ausgabe(f"   ✔ Bearbeiten-Seite: {d.bearbeiten_url}")
            preis = d.felder.get("preis")
            if not (preis and self._pruefen(preis.selektor)):
                d.bearbeiten_preis = self._klick_aufnehmen("   Klicke auf das Preisfeld … ")
            sel = self._klick_aufnehmen("   Klicke auf den Speichern-Knopf (wird NICHT ausgelöst) … ")
            if sel and sel != d.absenden:
                d.bearbeiten_absenden = sel


def _angebotsnummer(url: str) -> str | None:
    zahlen = re.findall(r"\d{4,}", urlsplit(url).path + "?" + urlsplit(url).query)
    return max(zahlen, key=len) if zahlen else None


def _vorlage_url(url: str, anzeige_id: str) -> str:
    """Macht aus einer Beispiel-Adresse eine Vorlage: /angebot/48151-spitzenslip -> /angebot/{id}."""
    teile = urlsplit(url)
    segmente = teile.path.split("/")
    for i, seg in enumerate(segmente):
        if anzeige_id in seg:
            segmente[i] = seg[: seg.index(anzeige_id)] + "{id}"
            pfad = "/".join(segmente)
            return teile._replace(path=pfad).geturl()
    return url.replace(anzeige_id, "{id}", 1)  # Nummer steht in der Query, z. B. ?id=48151


def _id_muster(anzeige_url: str) -> str:
    """Regex, die die Angebots-Nummer aus einer URL nach dem Veröffentlichen liest."""
    teile = urlsplit(anzeige_url)
    rest = teile.path + ("?" + teile.query if teile.query else "")
    davor = rest.split("{id}")[0][-15:] if "{id}" in rest else ""
    return re.escape(davor) + r"(\d+)" if davor else r"(\d{4,})"
