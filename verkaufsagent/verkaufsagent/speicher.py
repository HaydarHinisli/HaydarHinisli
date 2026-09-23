"""Persistenter Zustand aller Inserate (JSON, atomar geschrieben)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .modelle import Inserat


class Speicher:
    def __init__(self, ordner: Path):
        self.ordner = ordner
        self.ordner.mkdir(parents=True, exist_ok=True)
        self.datei = ordner / "inserate.json"
        self._inserate: dict[str, Inserat] = {}
        if self.datei.exists():
            roh = json.loads(self.datei.read_text(encoding="utf-8"))
            for eintrag in roh:
                i = Inserat.model_validate(eintrag)
                self._inserate[i.schluessel] = i

    def hole(self, produkt_id: str, plattform: str) -> Inserat | None:
        return self._inserate.get(f"{produkt_id}@{plattform}")

    def alle(self) -> list[Inserat]:
        return sorted(self._inserate.values(), key=lambda i: i.schluessel)

    def speichere(self, inserat: Inserat) -> None:
        self._inserate[inserat.schluessel] = inserat
        daten = json.dumps([i.model_dump(mode="json") for i in self.alle()], ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=self.ordner, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(daten)
        os.replace(tmp, self.datei)
