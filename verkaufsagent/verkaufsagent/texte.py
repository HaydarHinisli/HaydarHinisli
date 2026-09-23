"""Erzeugt für jedes Produkt und jede Plattform Titel und Beschreibung.

Eine Beschreibung ist Pflicht: Schlägt die KI fehl oder liefert sie
Ungültiges, wird eine vollständige Vorlage verwendet. Ein Inserat ohne
gültige Beschreibung wird nie veröffentlicht (siehe pruefe_texte).
"""
from __future__ import annotations

import base64
import io
import json
import logging
from typing import Callable

import anthropic
from pydantic import BaseModel

from .konfiguration import KiEinstellungen
from .modelle import Produkt, Texte
from .plattformdef import Definition

log = logging.getLogger(__name__)

BESCHREIBUNG_MIN = 80

SYSTEM = """Du schreibst Verkaufsangebote für private Verkäufe auf Online-Marktplätzen in Deutschland.

Regeln:
- Schreibe auf Deutsch, freundlich und persönlich, ohne Übertreibungen und höchstens 2 Emojis.
- Nenne nur Fakten aus den Produktdaten und dem, was auf den Fotos eindeutig erkennbar ist. Erfinde keine Maße, Materialien, Tragedauern oder Eigenschaften.
- Bekannte Mängel und Hinweise aus den Notizen MÜSSEN klar und ehrlich genannt werden.
- Bleibe dezent: keine expliziten sexuellen Beschreibungen, auch nicht auf Marktplätzen für Erwachsene.
- Nenne keinen Preis im Text (der steht im Preisfeld) und keine Telefonnummern, E-Mail-Adressen, Links oder Wege, die Plattform zu umgehen.
- Der Titel nennt den Artikel und – wenn sinnvoll – Größe/Farbe/Material. Kein Clickbait, keine GROSSBUCHSTABEN-Wörter.
- Halte dich an den Stil der jeweiligen Plattform (siehe Nachricht).
"""

DefinitionsQuelle = Callable[[str], Definition]


class _KiAntwort(BaseModel):
    titel: str
    beschreibung: str


def _schema(plattformen: list[str]) -> dict:
    eintrag = {
        "type": "object",
        "properties": {"titel": {"type": "string"}, "beschreibung": {"type": "string"}},
        "required": ["titel", "beschreibung"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {pl: eintrag for pl in plattformen},
        "required": list(plattformen),
        "additionalProperties": False,
    }


def _feldname(name: str) -> str:
    return name.replace("_", " ").capitalize()


def produktdaten_text(p: Produkt) -> str:
    zeilen = [f"Artikel: {p.name}", f"Zustand: {p.zustand.text}"]
    for label, wert in (("Marke", p.marke), ("Größe", p.groesse), ("Farbe", p.farbe), ("Material", p.material)):
        if wert:
            zeilen.append(f"{label}: {wert}")
    for pl in p.plattformen:
        for name, wert in p.optionen_fuer(pl).felder.items():
            zeilen.append(f"{_feldname(name)}: {wert}")
    zeilen.append(f"Versand möglich: {'ja' if p.versand else 'nein'}")
    if p.abholung:
        zeilen.append("Abholung möglich: ja")
    if p.notizen:
        zeilen.append(f"Hinweise (müssen erwähnt werden): {p.notizen}")
    return "\n".join(dict.fromkeys(zeilen))


def _bild_block(pfad) -> dict:
    from PIL import Image, ImageOps

    with Image.open(pfad) as bild:
        bild = ImageOps.exif_transpose(bild).convert("RGB")
        bild.thumbnail((1568, 1568))
        puffer = io.BytesIO()
        bild.save(puffer, format="JPEG", quality=85)
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.standard_b64encode(puffer.getvalue()).decode()},
    }


class TextGenerator:
    def __init__(self, einstellungen: KiEinstellungen, definitionen: DefinitionsQuelle,
                 client: anthropic.Anthropic | None = None):
        self.einst = einstellungen
        self.definitionen = definitionen
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def erzeuge(self, produkt: Produkt) -> dict[str, Texte]:
        plattformen = list(dict.fromkeys(produkt.plattformen))
        defs = {pl: self.definitionen(pl) for pl in plattformen}
        if self.einst.aktiv:
            try:
                texte = self._ki(produkt, defs)
                fehler = {pl: pruefe_texte(t, defs[pl]) for pl, t in texte.items()}
                if not any(fehler.values()):
                    return texte
                log.warning("KI-Texte für %s unvollständig (%s) – nutze Vorlage", produkt.id, fehler)
            except Exception as e:  # jeder KI-Fehler führt zur Vorlage – eine Beschreibung gibt es immer
                log.warning("KI-Beschreibung für %s fehlgeschlagen: %s – nutze Vorlage", produkt.id, e)
        return {pl: vorlage(produkt, pl, defs[pl]) for pl in plattformen}

    def _ki(self, produkt: Produkt, defs: dict[str, Definition]) -> dict[str, Texte]:
        inhalt: list[dict] = [_bild_block(f) for f in produkt.fotos[: self.einst.max_fotos]]
        vorgaben = "\n".join(
            f"- {pl} ({d.anzeigename}): Titel max. {d.titel_max} Zeichen, Beschreibung max. "
            f"{d.beschreibung_max} Zeichen. Stil: {d.stil or 'sachlich und freundlich'}"
            for pl, d in defs.items()
        )
        inhalt.append({
            "type": "text",
            "text": (
                f"Erstelle Titel und Beschreibung für diese Plattformen:\n{vorgaben}\n\n"
                f"Produktdaten:\n{produktdaten_text(produkt)}"
            ),
        })
        antwort = self.client.beta.messages.create(
            model=self.einst.modell,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": self.einst.effort, "format": {"type": "json_schema", "schema": _schema(list(defs))}},
            system=SYSTEM,
            messages=[{"role": "user", "content": inhalt}],
        )
        if antwort.stop_reason in ("refusal", "max_tokens"):
            raise ValueError(f"KI-Antwort unbrauchbar (stop_reason={antwort.stop_reason})")
        text = next(b.text for b in antwort.content if b.type == "text")
        daten = json.loads(text)
        ergebnis = {}
        for pl, d in defs.items():
            a = _KiAntwort.model_validate(daten[pl])
            ergebnis[pl] = Texte(titel=_kuerzen(a.titel.strip(), d.titel_max), beschreibung=a.beschreibung.strip(), quelle="ki")
        return ergebnis


def _kuerzen(text: str, laenge: int) -> str:
    if len(text) <= laenge:
        return text
    return text[:laenge].rsplit(" ", 1)[0].rstrip(" ,-–")


def vorlage(p: Produkt, plattform: str, definition: Definition) -> Texte:
    """Regelbasierte Beschreibung – garantiert vollständig, auch ohne KI."""
    titelteile = [p.marke, p.name] if p.marke and p.marke.lower() not in p.name.lower() else [p.name]
    if p.groesse and p.groesse.lower() not in p.name.lower():
        titelteile.append(f"Gr. {p.groesse}")
    if p.farbe and p.farbe.lower() not in p.name.lower():
        titelteile.append(p.farbe)
    titel = _kuerzen(" ".join(t for t in titelteile if t), definition.titel_max)

    details = []
    for label, wert in (("Marke", p.marke), ("Größe", p.groesse), ("Farbe", p.farbe), ("Material", p.material)):
        if wert:
            details.append(f"• {label}: {wert}")
    details.append(f"• Zustand: {p.zustand.text}")
    for name, wert in p.optionen_fuer(plattform).felder.items():
        details.append(f"• {_feldname(name)}: {wert}")

    abschnitte = [f"Hier biete ich an: {p.name}" + (f" von {p.marke}" if p.marke and p.marke.lower() not in p.name.lower() else "") + ".",
                  "\n".join(details)]
    if p.notizen:
        abschnitte.append(f"Bitte beachten: {p.notizen}")
    abschnitte.append("Weitere Details siehe Fotos. Bei Fragen oder Wünschen schreib mir gerne!")
    if p.versand:
        abschnitte.append("Der Versand erfolgt diskret verpackt.")
    if p.abholung:
        abschnitte.append("Abholung ist ebenfalls möglich.")
    return Texte(titel=titel, beschreibung="\n\n".join(abschnitte), quelle="vorlage")


def pruefe_texte(t: Texte, definition: Definition) -> list[str]:
    """Gibt eine Liste von Problemen zurück (leer = in Ordnung)."""
    probleme = []
    if not t.titel or len(t.titel) < 5:
        probleme.append("Titel fehlt/zu kurz")
    if len(t.titel) > definition.titel_max:
        probleme.append("Titel zu lang")
    if not t.beschreibung or len(t.beschreibung) < BESCHREIBUNG_MIN:
        probleme.append("Beschreibung fehlt/zu kurz")
    if len(t.beschreibung) > definition.beschreibung_max:
        probleme.append("Beschreibung zu lang")
    if "€" in t.beschreibung or "http" in t.beschreibung.lower() or "@" in t.beschreibung:
        probleme.append("Beschreibung enthält Preis, Link oder E-Mail")
    return probleme
