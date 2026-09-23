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

import anthropic
from pydantic import BaseModel, Field

from .konfiguration import KiEinstellungen
from .modelle import Plattform, Produkt, Texte

log = logging.getLogger(__name__)

# Plattform-Grenzen (bewusst etwas unter den tatsächlichen Limits)
GRENZEN = {
    Plattform.kleinanzeigen: {"titel_max": 65, "beschreibung_max": 4000},
    Plattform.vinted: {"titel_max": 60, "beschreibung_max": 2000},
}
BESCHREIBUNG_MIN = 80

SYSTEM = """Du schreibst Verkaufsanzeigen für private Verkäufe auf Kleinanzeigen und Vinted (Deutschland).

Regeln:
- Schreibe auf Deutsch, freundlich, sachlich, ohne Übertreibungen und ohne Emojis-Flut (höchstens 2).
- Nenne nur Fakten aus den Produktdaten und dem, was auf den Fotos eindeutig erkennbar ist. Erfinde keine Maße, Materialien, Neupreise oder Eigenschaften.
- Bekannte Mängel aus den Notizen MÜSSEN klar und ehrlich genannt werden.
- Nenne keinen Preis im Text (der steht im Preisfeld) und keine Telefonnummern, E-Mail-Adressen oder Links.
- Der Titel beginnt mit Marke (falls bekannt) und Artikel und enthält Größe/Farbe, wenn sinnvoll. Kein Clickbait, keine GROSSBUCHSTABEN-Wörter.
- Kleinanzeigen: Beschreibung mit kurzen Absätzen; Zustand, Details, Versand/Abholung, Hinweis "Privatverkauf, keine Garantie oder Rücknahme".
- Vinted: kompakter, Stichpunkte erlaubt, am Ende 3–5 passende Hashtags (#marke #artikel ...).
"""


class _KiAntwort(BaseModel):
    titel: str = Field(description="Anzeigentitel")
    beschreibung: str = Field(description="Anzeigentext")


_SCHEMA = {
    "type": "object",
    "properties": {
        "kleinanzeigen": {
            "type": "object",
            "properties": {"titel": {"type": "string"}, "beschreibung": {"type": "string"}},
            "required": ["titel", "beschreibung"],
            "additionalProperties": False,
        },
        "vinted": {
            "type": "object",
            "properties": {"titel": {"type": "string"}, "beschreibung": {"type": "string"}},
            "required": ["titel", "beschreibung"],
            "additionalProperties": False,
        },
    },
    "required": ["kleinanzeigen", "vinted"],
    "additionalProperties": False,
}


def produktdaten_text(p: Produkt) -> str:
    zeilen = [f"Artikel: {p.name}", f"Zustand: {p.zustand.text}"]
    for label, wert in (("Marke", p.marke), ("Größe", p.groesse), ("Farbe", p.farbe), ("Material", p.material)):
        if wert:
            zeilen.append(f"{label}: {wert}")
    zeilen.append(f"Versand möglich: {'ja' if p.versand else 'nein'}")
    zeilen.append(f"Abholung möglich: {'ja' if p.abholung else 'nein'}")
    if p.notizen:
        zeilen.append(f"Hinweise/Mängel (müssen erwähnt werden): {p.notizen}")
    return "\n".join(zeilen)


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
    def __init__(self, einstellungen: KiEinstellungen, client: anthropic.Anthropic | None = None):
        self.einst = einstellungen
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def erzeuge(self, produkt: Produkt) -> dict[Plattform, Texte]:
        if self.einst.aktiv:
            try:
                texte = self._ki(produkt)
                fehler = {pl: pruefe_texte(t, pl, produkt) for pl, t in texte.items()}
                if not any(fehler.values()):
                    return texte
                log.warning("KI-Texte für %s unvollständig (%s) – nutze Vorlage", produkt.id, fehler)
            except Exception as e:  # jeder KI-Fehler führt zur Vorlage – eine Beschreibung gibt es immer
                log.warning("KI-Beschreibung für %s fehlgeschlagen: %s – nutze Vorlage", produkt.id, e)
        return {pl: vorlage(produkt, pl) for pl in Plattform}

    def _ki(self, produkt: Produkt) -> dict[Plattform, Texte]:
        inhalt: list[dict] = [_bild_block(f) for f in produkt.fotos[: self.einst.max_fotos]]
        inhalt.append({
            "type": "text",
            "text": (
                "Erstelle Titel und Beschreibung für beide Plattformen.\n"
                f"Titel Kleinanzeigen max. {GRENZEN[Plattform.kleinanzeigen]['titel_max']} Zeichen, "
                f"Vinted max. {GRENZEN[Plattform.vinted]['titel_max']} Zeichen.\n\n"
                f"Produktdaten:\n{produktdaten_text(produkt)}"
            ),
        })
        antwort = self.client.beta.messages.create(
            model=self.einst.modell,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            thinking={"type": "adaptive"},
            output_config={"effort": self.einst.effort, "format": {"type": "json_schema", "schema": _SCHEMA}},
            system=SYSTEM,
            messages=[{"role": "user", "content": inhalt}],
        )
        if antwort.stop_reason in ("refusal", "max_tokens"):
            raise ValueError(f"KI-Antwort unbrauchbar (stop_reason={antwort.stop_reason})")
        text = next(b.text for b in antwort.content if b.type == "text")
        daten = json.loads(text)
        ergebnis = {}
        for pl in Plattform:
            a = _KiAntwort.model_validate(daten[pl.value])
            ergebnis[pl] = Texte(titel=_kuerzen(a.titel.strip(), GRENZEN[pl]["titel_max"]), beschreibung=a.beschreibung.strip(), quelle="ki")
        return ergebnis


def _kuerzen(text: str, laenge: int) -> str:
    if len(text) <= laenge:
        return text
    return text[:laenge].rsplit(" ", 1)[0].rstrip(" ,-–")


def vorlage(p: Produkt, plattform: Plattform) -> Texte:
    """Regelbasierte Beschreibung – garantiert vollständig, auch ohne KI."""
    titelteile = [p.marke, p.name] if p.marke and p.marke.lower() not in p.name.lower() else [p.name]
    if p.groesse:
        titelteile.append(f"Gr. {p.groesse}")
    if p.farbe:
        titelteile.append(p.farbe)
    titel = _kuerzen(" ".join(t for t in titelteile if t), GRENZEN[plattform]["titel_max"])

    details = []
    for label, wert in (("Marke", p.marke), ("Größe", p.groesse), ("Farbe", p.farbe), ("Material", p.material)):
        if wert:
            details.append(f"• {label}: {wert}")
    details.append(f"• Zustand: {p.zustand.text}")

    uebergabe = []
    if p.versand:
        uebergabe.append("Versand möglich")
    if p.abholung:
        uebergabe.append("Abholung möglich")

    abschnitte = [f"Zum Verkauf steht: {p.name}" + (f" von {p.marke}" if p.marke and p.marke.lower() not in p.name.lower() else "") + ".",
                  "\n".join(details)]
    if p.notizen:
        abschnitte.append(f"Bitte beachten: {p.notizen}")
    abschnitte.append("Weitere Details siehe Fotos. Bei Fragen gerne melden!")
    if uebergabe:
        abschnitte.append(" / ".join(uebergabe) + ".")
    if plattform == Plattform.kleinanzeigen:
        abschnitte.append("Privatverkauf, daher keine Garantie oder Rücknahme.")
    else:
        tags = [p.marke, p.name.split()[0] if p.name else None, p.farbe]
        abschnitte.append(" ".join("#" + "".join(t.lower().split()) for t in tags if t))
    return Texte(titel=titel, beschreibung="\n\n".join(abschnitte), quelle="vorlage")


def pruefe_texte(t: Texte, plattform: Plattform, produkt: Produkt) -> list[str]:
    """Gibt eine Liste von Problemen zurück (leer = in Ordnung)."""
    probleme = []
    g = GRENZEN[plattform]
    if not t.titel or len(t.titel) < 5:
        probleme.append("Titel fehlt/zu kurz")
    if len(t.titel) > g["titel_max"]:
        probleme.append("Titel zu lang")
    if not t.beschreibung or len(t.beschreibung) < BESCHREIBUNG_MIN:
        probleme.append("Beschreibung fehlt/zu kurz")
    if len(t.beschreibung) > g["beschreibung_max"]:
        probleme.append("Beschreibung zu lang")
    if "€" in t.beschreibung or "http" in t.beschreibung.lower() or "@" in t.beschreibung:
        probleme.append("Beschreibung enthält Preis, Link oder E-Mail")
    return probleme
