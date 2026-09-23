"""Laden von config.yaml und produkte.yaml."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .modelle import Produkt


class PreisRegeln(BaseModel):
    # Erste Reduzierung frühestens nach so vielen Tagen online
    erste_reduzierung_nach_tagen: int = Field(14, ge=1)
    # Mindestabstand zwischen zwei Reduzierungen
    abstand_tage: int = Field(7, ge=1)
    # Kumulierte Rabattstufen (Anteil vom Originalpreis), max. 0.30
    stufen: list[float] = Field(default_factory=lambda: [0.05, 0.10, 0.15, 0.20, 0.25, 0.30])
    # Ab so vielen Favoriten gilt das Interesse als hoch -> keine Reduzierung
    favoriten_hoch: int = 5
    # Ab so vielen Nachrichten gilt das Interesse als hoch -> keine Reduzierung
    nachrichten_hoch: int = 3
    # Aufrufe pro Tag, unter denen die Nachfrage als schwach gilt
    aufrufe_pro_tag_schwach: float = 3.0
    # Ohne Statistikdaten wird nie mehr als dieser Anteil reduziert
    max_rabatt_ohne_statistik: float = Field(0.15, ge=0, le=0.30)
    # Statistik älter als so viele Stunden gilt als unbekannt
    statistik_max_alter_stunden: int = 48


class KiEinstellungen(BaseModel):
    aktiv: bool = True
    modell: str = "claude-opus-5"
    effort: str = Field("medium", pattern="^(low|medium|high|xhigh|max)$")
    max_fotos: int = Field(6, ge=0, le=20)


class BrowserEinstellungen(BaseModel):
    headless: bool = True
    langsam_ms: int = 150
    timeout_ms: int = 30000
    # Optional: eigener Chrome/Chromium statt des von Playwright installierten
    programm: str | None = None


class Konfiguration(BaseModel):
    postleitzahl: str = Field("", description="Für Kleinanzeigen erforderlich")
    kontakt_name: str = ""
    # true: veröffentlicht ohne Rückfrage. false: füllt aus, macht Screenshot, wartet auf Enter.
    auto_veroeffentlichen: bool = False
    # Pause zwischen zwei Inseraten (Sekunden) – schont Konto und Plattform
    pause_zwischen_inseraten_s: int = Field(90, ge=10)
    max_neue_inserate_pro_lauf: int = Field(10, ge=1)
    preise: PreisRegeln = Field(default_factory=PreisRegeln)
    ki: KiEinstellungen = Field(default_factory=KiEinstellungen)
    browser: BrowserEinstellungen = Field(default_factory=BrowserEinstellungen)
    datenordner: Path = Path("daten")


def lade_konfiguration(pfad: Path) -> Konfiguration:
    daten = yaml.safe_load(pfad.read_text(encoding="utf-8")) if pfad.exists() else {}
    konf = Konfiguration.model_validate(daten or {})
    if not konf.datenordner.is_absolute():
        konf.datenordner = (pfad.parent / konf.datenordner).resolve()
    return konf


def lade_produkte(pfad: Path) -> list[Produkt]:
    daten = yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}
    produkte = [Produkt.model_validate(p) for p in daten.get("produkte", [])]
    basis = pfad.parent
    ids: set[str] = set()
    for p in produkte:
        if p.id in ids:
            raise ValueError(f"Doppelte Produkt-ID: {p.id}")
        ids.add(p.id)
        p.fotos = _fotos_aufloesen(basis, p.fotos)
    return produkte


_BILDENDUNGEN = {".jpg", ".jpeg", ".png", ".webp"}


def _fotos_aufloesen(basis: Path, eintraege: list[Path]) -> list[Path]:
    """Einträge können einzelne Dateien oder Ordner sein."""
    ergebnis: list[Path] = []
    for e in eintraege:
        pfad = e if e.is_absolute() else basis / e
        if pfad.is_dir():
            ergebnis.extend(sorted(f for f in pfad.iterdir() if f.suffix.lower() in _BILDENDUNGEN))
        elif pfad.is_file():
            ergebnis.append(pfad)
        else:
            raise FileNotFoundError(f"Foto nicht gefunden: {pfad}")
    return ergebnis
