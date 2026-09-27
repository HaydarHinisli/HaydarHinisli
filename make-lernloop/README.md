# Make-Lernloop

Lokales System, das schrittweise ein **belegbares** Verständnis von Make.com aufbaut –
mit Quellenbelegen, getrennten Übungs- und Prüfaufgaben und einem ehrlichen Vergleich
gegen reine Dokumentationssuche.

Grundlage: *Entwicklungsbrief: Lernsystem für Make.com* (Haydar Hinisli, 27.09.2026).

## Stand

**Phase 1 (Planung)** – dieses Verzeichnis enthält die Planungsunterlagen. Es gibt noch
keinen Lernloop-Code; laut Brief (§15) werden vor Entwicklungsbeginn fachliche
Verantwortung, Ressourcenlimits und Bewertungskriterien festgelegt.

| Datei | Inhalt |
|---|---|
| [`docs/01-phase1-planung.md`](docs/01-phase1-planung.md) | Architektur, Datenmodell, Quellenrahmen, erster Themenbereich, Prüfverfahren, Hardware-/Modellentscheidung, Kostenannahmen |
| [`docs/02-offene-entscheidungen.md`](docs/02-offene-entscheidungen.md) | Entscheidungen, die vor Phase 2 vom Auftraggeber zu treffen sind (mit Empfehlung) |
| [`config/limits.example.toml`](config/limits.example.toml) | Beispielkonfiguration für programmseitig durchgesetzte Limits (ohne Zugangsdaten) |
| [`scripts/hardware_check.py`](scripts/hardware_check.py) | Liest Betriebssystem, Chip, RAM und freien Speicher des Laptops aus – ohne Netzwerkzugriff |

## Nächster Schritt für dich

1. Auf deinem Laptop ausführen und die Ausgabe zurückgeben:

   ```bash
   python3 make-lernloop/scripts/hardware_check.py
   ```

   Das Skript liest nur lokale Systemwerte, sendet nichts und schreibt keine Dateien.

2. Die Entscheidungen in [`docs/02-offene-entscheidungen.md`](docs/02-offene-entscheidungen.md)
   beantworten (für jede gibt es eine Empfehlung – „Empfehlung übernehmen“ reicht).

Danach kann Phase 2 (vollständiger erster Lernzyklus) beginnen.
