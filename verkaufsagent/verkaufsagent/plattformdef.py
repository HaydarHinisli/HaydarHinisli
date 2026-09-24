"""Plattform-Definitionen.

Jede Plattform (Crazyslip, Creamsi, …) wird durch eine YAML-Datei beschrieben:
Adressen, Formularfelder und Selektoren. Mitgeliefert werden Vorlagen in
verkaufsagent/plattformen/definitionen/. Mit 'verkaufsagent einrichten <name>'
werden die Selektoren im Browser angelernt und in
<datenordner>/plattformen/<name>.yaml gespeichert (überschreibt die Vorlage).
Für eine neue Seite genügt eine neue Datei in diesem Ordner.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

_VORLAGEN = Path(__file__).resolve().parent / "plattformen" / "definitionen"

FELDTYPEN = ("text", "datei", "auswahl", "klick", "haken")


class Feld(BaseModel):
    typ: str = Field("text", pattern="^(" + "|".join(FELDTYPEN) + ")$")
    selektor: list[str] = Field(default_factory=list)
    pflicht: bool = False
    beschriftung: str | None = None  # Anzeigename im Einrichtungs-Assistenten


class Definition(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9_-]+$")
    anzeigename: str
    basis_url: str
    login_url: str | None = None
    neu_url: str | None = None
    # Klicks, die nach dem Öffnen von neu_url nötig sind, bis das Formular erscheint
    # (für Seiten, deren Formular keine eigene Adresse hat). Je Schritt eine Liste von Selektoren.
    navigation: list[list[str]] = Field(default_factory=list)
    bearbeiten_url: str | None = None  # mit {id}
    anzeige_url: str | None = None     # mit {id}
    id_muster: str = r"(\d{4,})"
    nicht_angemeldet_wenn: list[str] = Field(default_factory=lambda: ["login", "anmelden", "signin", "einloggen", "register"])
    verkauft_texte: list[str] = Field(default_factory=list)
    titel_max: int = 60
    beschreibung_max: int = 2000
    stil: str = ""
    sprache: str = Field("de", pattern="^(de|en)$")  # Sprache der Angebotstexte
    # Werte für Formularfelder, wenn das Produkt keinen eigenen Wert hat (z. B. waehrung: EUR)
    standardwerte: dict[str, str] = Field(default_factory=dict)
    felder: dict[str, Feld] = Field(default_factory=dict)
    absenden: list[str] = Field(default_factory=list)
    bearbeiten_preis: list[str] = Field(default_factory=list)     # leer = wie Feld 'preis'
    bearbeiten_absenden: list[str] = Field(default_factory=list)  # leer = wie 'absenden'
    aufrufe: list[str] = Field(default_factory=list)
    # Automatische Anmeldung (angelernt mit 'login <plattform>')
    login_klicks: list[list[str]] = Field(default_factory=list)   # Weg zum Login-Formular
    login_benutzer: list[str] = Field(default_factory=list)
    login_passwort: list[str] = Field(default_factory=list)
    login_absenden: list[str] = Field(default_factory=list)
    abgemeldet_zeichen: list[str] = Field(default_factory=list)   # sichtbar = nicht angemeldet (z. B. LOGIN-Link)
    favoriten: list[str] = Field(default_factory=list)

    @property
    def login_eingerichtet(self) -> bool:
        return bool(self.login_benutzer and self.login_passwort and self.login_absenden)

    @property
    def eingerichtet(self) -> bool:
        return bool(self.neu_url and self.absenden and all(f.selektor for f in self.felder.values() if f.pflicht))

    def fehlend(self) -> list[str]:
        fehlt = [] if self.neu_url else ["neu_url"]
        fehlt += [n for n, f in self.felder.items() if f.pflicht and not f.selektor]
        if not self.absenden:
            fehlt.append("absenden")
        return fehlt

    def anzeige_id(self, url: str) -> str | None:
        treffer = re.search(self.id_muster, url)
        return treffer.group(1) if treffer else None


class Register:
    """Findet alle Plattform-Definitionen (Vorlagen + eigene)."""

    def __init__(self, datenordner: Path):
        self.eigene = datenordner / "plattformen"

    def namen(self) -> list[str]:
        dateien = list(_VORLAGEN.glob("*.yaml")) + (list(self.eigene.glob("*.yaml")) if self.eigene.exists() else [])
        return sorted({d.stem for d in dateien})

    def lade(self, name: str) -> Definition:
        daten: dict = {}
        for datei in (_VORLAGEN / f"{name}.yaml", self.eigene / f"{name}.yaml"):
            if datei.exists():
                daten = _verschmelzen(daten, yaml.safe_load(datei.read_text(encoding="utf-8")) or {})
        if not daten:
            raise ValueError(f"Unbekannte Plattform '{name}'. Verfügbar: {', '.join(self.namen()) or '-'}")
        daten.setdefault("name", name)
        return Definition.model_validate(daten)

    def speichere(self, definition: Definition) -> Path:
        self.eigene.mkdir(parents=True, exist_ok=True)
        pfad = self.eigene / f"{definition.name}.yaml"
        pfad.write_text(
            "# Angelernt mit 'verkaufsagent einrichten'. Selektoren dürfen von Hand angepasst werden.\n"
            + yaml.safe_dump(definition.model_dump(exclude_none=True), allow_unicode=True, sort_keys=False, width=1000),
            encoding="utf-8",
        )
        return pfad


def _verschmelzen(basis: dict, ueber: dict) -> dict:
    ergebnis = dict(basis)
    for k, v in ueber.items():
        ergebnis[k] = _verschmelzen(ergebnis[k], v) if isinstance(v, dict) and isinstance(ergebnis.get(k), dict) else v
    return ergebnis
