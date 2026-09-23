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
    if (tag === 'button' || el.getAttribute('role') === 'button') {
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
    ev.preventDefault(); ev.stopPropagation(); ev.stopImmediatePropagation();
    if (ev.type !== 'click') return;
    const el = ziel(ev.target);
    window.__va.element = el;
    window.__va.auswahl = {selektoren: selektoren(el), tag: el.tagName.toLowerCase(), text: (el.innerText || '').trim().slice(0, 40)};
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
        self.frage(f"\n1) Melde dich im Browser bei {d.anzeigename} an (falls nötig) und öffne die Seite, auf der man\n"
                   "   ein NEUES Angebot erstellt. Dann hier Enter drücken … ")
        d.neu_url = self.page.url
        self.ausgabe(f"   ✔ Formular-Adresse: {d.neu_url}")

        self.ausgabe("\n2) Jetzt die Felder: Klicke im Browser auf das genannte Feld und drücke dann hier Enter.\n"
                     "   (Klicks werden abgefangen – es wird nichts ausgelöst. Nur Enter ohne Klick = überspringen.)")
        for nr, (name, feld) in enumerate(d.felder.items(), 1):
            text = (f"   [{nr}/{len(d.felder)}] {feld.beschriftung or name}: klicke auf {HINWEIS[feld.typ]}"
                    f"{' (Pflicht)' if feld.pflicht else ''} … ")
            sel = self._klick_aufnehmen(text, datei=feld.typ == "datei")
            if sel:
                feld.selektor = sel
                self.ausgabe(f"      ✔ {sel[0]}")
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
            self.ausgabe(f"   ✔ {sel[0]}")

        self._angebotsseiten(d)
        pfad = self.register.speichere(d)
        self.ausgabe(f"\nGespeichert: {pfad}")
        fehlt = d.fehlend()
        self.ausgabe("✔ Einrichtung vollständig – der Agent kann jetzt inserieren." if not fehlt
                     else f"⚠ Noch nicht vollständig, es fehlt: {', '.join(fehlt)}. 'einrichten {d.name}' erneut ausführen.")
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
