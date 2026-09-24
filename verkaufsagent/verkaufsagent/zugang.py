"""Zugangsdaten für die automatische Anmeldung.

Auf dem Mac liegt das Passwort im Schlüsselbund (Programm „Schlüsselbundverwaltung“),
nur der Benutzername steht in einer Datei. Auf anderen Systemen steht beides in einer
Datei, die nur der eigene Benutzer lesen darf.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def _datei(datenordner: Path, plattform: str) -> Path:
    return datenordner / "zugang" / f"{plattform}.json"


def _dienst(plattform: str) -> str:
    return f"verkaufsagent-{plattform}"


def _mac() -> bool:
    return sys.platform == "darwin" and os.environ.get("VERKAUFSAGENT_KEIN_SCHLUESSELBUND") != "1"


def speichere_zugang(datenordner: Path, plattform: str, benutzer: str, passwort: str) -> None:
    datei = _datei(datenordner, plattform)
    datei.parent.mkdir(parents=True, exist_ok=True)
    daten = {"benutzer": benutzer}
    if _mac():
        subprocess.run(["security", "add-generic-password", "-U", "-a", benutzer, "-s", _dienst(plattform),
                        "-w", passwort], check=True, capture_output=True)
    else:
        daten["passwort"] = passwort
    datei.write_text(json.dumps(daten), encoding="utf-8")
    os.chmod(datei, 0o600)


def lade_zugang(datenordner: Path, plattform: str) -> tuple[str, str] | None:
    datei = _datei(datenordner, plattform)
    if not datei.exists():
        return None
    daten = json.loads(datei.read_text(encoding="utf-8"))
    if "passwort" in daten:
        return daten["benutzer"], daten["passwort"]
    if _mac():
        ergebnis = subprocess.run(["security", "find-generic-password", "-a", daten["benutzer"], "-s",
                                   _dienst(plattform), "-w"], capture_output=True, text=True)
        if ergebnis.returncode == 0:
            return daten["benutzer"], ergebnis.stdout.rstrip("\n")
    return None
