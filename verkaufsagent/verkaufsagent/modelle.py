"""Datenmodelle: Produkte (Eingabe) und Inserate (Zustand)."""
from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

# Harte Obergrenze für Preisnachlässe. Wird überall im Code erzwungen,
# unabhängig von Konfiguration oder KI-Vorschlägen.
MAX_RABATT_ABSOLUT = 0.30


class Zustand(str, Enum):
    neu_mit_etikett = "neu_mit_etikett"
    neu = "neu"
    sehr_gut = "sehr_gut"
    gut = "gut"
    zufriedenstellend = "zufriedenstellend"

    @property
    def text(self) -> str:
        return {
            "neu_mit_etikett": "Neu mit Etikett",
            "neu": "Neu ohne Etikett",
            "sehr_gut": "Sehr gut",
            "gut": "Gut",
            "zufriedenstellend": "Zufriedenstellend",
        }[self.value]


class Plattform(str, Enum):
    kleinanzeigen = "kleinanzeigen"
    vinted = "vinted"


class KleinanzeigenOptionen(BaseModel):
    kategorie: list[str] = Field(default_factory=list, description="Pfad, z. B. ['Mode & Beauty', 'Herrenbekleidung']")
    preistyp: str = Field("VB", pattern="^(VB|Festpreis)$")


class VintedOptionen(BaseModel):
    kategorie: list[str] = Field(default_factory=list, description="Pfad, z. B. ['Herren', 'Kleidung', 'Jacken']")
    paketgroesse: str = Field("M", pattern="^(S|M|L)$")


class Produkt(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    name: str
    preis: float = Field(gt=0, description="Dein Wunschpreis in EUR – wird so inseriert")
    mindestpreis: float | None = Field(None, gt=0, description="Optional: absolute Untergrenze")
    max_rabatt_prozent: float = Field(30, ge=0, le=30)
    verhandelbar: bool = True
    zustand: Zustand
    marke: str | None = None
    groesse: str | None = None
    farbe: str | None = None
    material: str | None = None
    notizen: str | None = Field(None, description="Fakten/Mängel, die in die Beschreibung müssen")
    fotos: list[Path] = Field(default_factory=list)
    plattformen: list[Plattform] = Field(default_factory=lambda: [Plattform.kleinanzeigen, Plattform.vinted])
    versand: bool = True
    abholung: bool = True
    kleinanzeigen: KleinanzeigenOptionen = Field(default_factory=KleinanzeigenOptionen)
    vinted: VintedOptionen = Field(default_factory=VintedOptionen)

    @field_validator("preis", "mindestpreis")
    @classmethod
    def _runden(cls, v: float | None) -> float | None:
        return None if v is None else round(v, 2)

    @model_validator(mode="after")
    def _pruefen(self) -> "Produkt":
        if self.mindestpreis is not None and self.mindestpreis > self.preis:
            raise ValueError(f"{self.id}: mindestpreis ({self.mindestpreis}) liegt über preis ({self.preis})")
        return self

    def untergrenze(self) -> float:
        """Niedrigster Preis, der jemals verlangt oder akzeptiert werden darf."""
        rabatt = min(self.max_rabatt_prozent / 100, MAX_RABATT_ABSOLUT) if self.verhandelbar else 0.0
        grenze = self.preis * (1 - rabatt)
        if self.mindestpreis is not None:
            grenze = max(grenze, self.mindestpreis)
        # auf volle Cent AUFrunden, damit nie mehr als der erlaubte Rabatt gewährt wird
        return math.ceil(round(grenze * 100, 6)) / 100


class Texte(BaseModel):
    """Plattform-spezifischer Titel + Beschreibung."""
    titel: str
    beschreibung: str
    quelle: str = "ki"  # "ki" oder "vorlage"


class Preisaenderung(BaseModel):
    zeitpunkt: datetime
    alt: float
    neu: float
    grund: str


class Inserat(BaseModel):
    produkt_id: str
    plattform: Plattform
    status: str = "entwurf"  # entwurf | online | verkauft | fehler | entfernt
    anzeige_id: str | None = None
    url: str | None = None
    titel: str | None = None
    beschreibung: str | None = None
    preis_aktuell: float | None = None
    online_seit: datetime | None = None
    letzte_preisaenderung: datetime | None = None
    preisverlauf: list[Preisaenderung] = Field(default_factory=list)
    aufrufe: int | None = None
    favoriten: int | None = None
    nachrichten: int | None = None
    statistik_stand: datetime | None = None
    fehler: str | None = None

    @property
    def schluessel(self) -> str:
        return f"{self.produkt_id}@{self.plattform.value}"
