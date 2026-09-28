# Make-Lernloop

Lokales System, das schrittweise ein **belegbares** Verständnis von Make.com aufbaut –
mit wörtlich geprüften Quellenbelegen, nachvollziehbarem Status je Erkenntnis und
ehrlichem „ungeklärt“, wenn die Doku etwas nicht belegt.

Grundlage: *Entwicklungsbrief: Lernsystem für Make.com* (27.09.2026).
Planung: [`docs/01-phase1-planung.md`](docs/01-phase1-planung.md) ·
Entscheidungen: [`docs/02-offene-entscheidungen.md`](docs/02-offene-entscheidungen.md)

## Stand

**Phase 2 (erster Lernzyklus) – Version 0.1.** Läuft über dein **Claude-Pro-Abo** (Claude Code),
ohne zusätzliche Kosten. Nur Python-Standardbibliothek, keine weiteren Pakete.

| Funktion | Stand |
|---|---|
| Lernsitzung als Zustandsautomat mit Checkpoints, Wiederaufnahme, Pause bei Nutzungslimit | ✅ |
| Abgesicherter Abruf (nur freigegebene Hosts, https, keine internen Adressen, robots.txt, Ratenlimit) | ✅ |
| Seitenkatalog aus Sitemaps + Links, lokale Suche | ✅ |
| Zitatprüfung durch das Programm, Statusregeln, Konflikte, Nachfolgefassungen, „veraltet“-Erkennung | ✅ |
| Limits je Sitzung (Zeit, Modellaufrufe, Abrufe) und je Tag (Pro-Kontingent) | ✅ |
| Übungsaufgaben mit menschlich bestätigter Musterlösung, menschliche Bewertung | ✅ |
| `ask` mit Variante A (nur Doku) und B (Doku + Lernspeicher) | ✅ |
| Berichte, Abdeckung je Themenkatalog, Export, Sicherung/Wiederherstellung | ✅ |
| Verschlüsselte, zurückgehaltene Prüfsammlung + A/B-Vergleichslauf | Phase 3 |
| Nutzung des Wissens aus Claude heraus (MCP-Schnittstelle, Export für Claude-Projekte) | nach Phase 2 |
| API-Anbindung | gesperrt bis Entscheidung E2 |

Getestet mit 33 automatischen Tests (simuliertes Netz und Modell). Gegen die echte
Make-Dokumentation lief der Loop noch nicht – der erste echte Lauf ist deiner.

## Einrichtung (einmalig)

1. **Python 3.9 oder neuer** – prüfen mit `python3 --version` (das vorinstallierte Python auf dem Mac reicht).
2. **Claude Code** installieren (offizielle Anleitung: <https://code.claude.com/docs>), z. B.
   - macOS/Linux: `curl -fsSL https://claude.ai/install.sh | bash`
   - Windows (PowerShell): `irm https://claude.ai/install.ps1 | iex`
3. Einmal `claude` im Terminal starten und **mit deinem Pro-Konto anmelden**, dann beenden.
   Einen API-Schlüssel brauchst du nicht. Ist `ANTHROPIC_API_KEY` gesetzt, entfernt der
   Lernloop ihn für seine Aufrufe, damit garantiert über das Abo abgerechnet wird.
4. Repository holen und einrichten:

   ```bash
   git clone <dieses Repository>
   cd <Repository>/make-lernloop
   python3 -m lernloop init              # legt lernloop.toml, data/ und den Themenkatalog an
   python3 -m lernloop doctor --test-call  # prüft Claude Code mit einem kleinen Testaufruf
   ```

5. **Nutzungsbedingungen prüfen (Entscheidung E5)** – Pflicht vor dem ersten Abruf:
   <https://help.make.com/robots.txt>, <https://developers.make.com/robots.txt> und die
   Nutzungsbedingungen von Make lesen. Ist automatisiertes Lesen erlaubt, in `lernloop.toml`
   `terms_reviewed = true` setzen. Nur wenn auch das Speichern ganzer Seiten erlaubt ist,
   zusätzlich `store_raw_html = true` (sonst werden nur Abschnittstexte für Zitate gespeichert).
   Solange `terms_reviewed = false` ist, verweigert das Programm jeden Netzwerkzugriff.

## Benutzung

```bash
python3 -m lernloop catalog refresh          # Seitenkatalog aus den Sitemaps aufbauen
python3 -m lernloop plan                     # Themen und Lernziele
python3 -m lernloop learn --topic T01        # eine Lernsitzung (nächstes offenes Lernziel)
python3 -m lernloop learn --resume           # unterbrochene Sitzung fortsetzen
python3 -m lernloop report coverage          # Abdeckung im Themenkatalog
python3 -m lernloop review list              # Entwürfe, Befunde, unbewertete Übungen
python3 -m lernloop claim ERK-000001         # Erkenntnis mit Belegen und Verlauf
python3 -m lernloop ask "Was gibt der Iterator aus?"            # Variante B
python3 -m lernloop ask "Was gibt der Iterator aus?" --variante A
python3 -m lernloop backup                   # Sicherung (mit Prüfsumme)
python3 -m lernloop export                   # alles als JSON Lines
```

Nach jeder Sitzung erscheint ein Bericht im Terminal und als HTML-Datei unter `data/reports/`.

### Was du als Mensch tust

- `review confirm ERK-… --reason "…"` – gefolgerte Aussage nach eigener Prüfung bestätigen.
- `review retract ERK-… --reason "…"` – falsche Aussage zurückziehen.
- `review narrow ERK-… --statement "…" --reason "zu breit"` – engere Nachfolgefassung anlegen.
- `review resolve KON-… --reason "…"` – Befund/Widerspruch als geklärt markieren.
- `task add aufgaben.json` – Übungsaufgaben mit **von dir bzw. einer Make-kundigen Person
  bestätigter** Musterlösung importieren (Format siehe unten).
- `review grade VER-… --bestanden|--nicht-bestanden --reason "…"` – Übungsantwort bewerten.
  Nur bestandene, menschlich bewertete Übungen heben Erkenntnisse auf „theoretisch geprüft“.

```json
[{"topic_id": "T01", "task_type": "vorhersage",
  "prompt": "Ein Modul liefert ein Array mit 3 Elementen an einen Iterator. Wie oft läuft das Folgemodul?",
  "expected": "3-mal", "expected_source": "mensch", "approved_by": "Haydar"}]
```

## Mit dem Wissen arbeiten: Claude-Code-Chat „make-wissen“

Der Lernloop bereitet das Wissen vor; genutzt wird es beim Arbeiten mit Make in einem normalen
Claude-Code-Fenster. Einmalig eintragen:

```bash
python3 -m lernloop mcp-install
```

Danach in einem **neuen** Claude-Code-Fenster (`claude`, in jedem Ordner) mit `/mcp` prüfen, dass
„make-wissen“ verbunden ist. Claude schlägt dann bei Make-Fragen selbst im geprüften Speicher nach,
nennt die Erkenntnis-IDs (ERK-…) und sagt offen, wenn etwas nicht belegt ist.

- Nur lesend: Der Chat kann den Speicher nicht verändern. Lernen läuft weiter über `lernloop learn`.
- Kein zusätzlicher Verbrauch durch den Speicher selbst; es zählt nur der normale Chat.
- Neue Lernergebnisse stehen dem Chat sofort zur Verfügung.
- Entfernen: `claude mcp remove make-wissen --scope user`

## Statusregeln (vom Programm erzwungen)

| Status | Wann |
|---|---|
| `entwurf` | neu erfasst, oder Regeln für „dokumentiert“ nicht erfüllt (Grund steht dabei) |
| `dokumentiert` | Zitat steht wörtlich im gespeicherten Abschnitt offizieller Doku, direkt zitiert, kein offener Befund. Gefolgerte Aussagen und KI-Schlussfolgerungen nur nach menschlicher Bestätigung |
| `theoretisch_geprüft` | zusätzlich eine bestandene, menschlich bewertete Übung |
| `praktisch_bestätigt` | in Version 1 gesperrt (keine Experimente) |
| `widersprüchlich` / `veraltet` / `zurückgezogen` / `ungeklärt` | mit Begründung; veraltet automatisch, wenn das Zitat in einer neueren Fassung der Seite fehlt |

## Was den Laptop verlässt

An Claude gehen nur: die Systemanweisung, das Lernziel bzw. die Frage, Auszüge aus
öffentlicher Make-Dokumentation und bereits gespeicherte Erkenntnisse. Keine Dateien,
keine Zugangsdaten. Claude hat in diesen Aufrufen **keine Werkzeuge** (kein Dateizugriff,
keine Befehle, kein Webzugriff); jeder Aufruf läuft in einem leeren temporären Ordner.
Jeder Aufruf wird mit Anfrage und Antwort unter `data/logs/calls/` protokolliert.

## Sicherung und Wiederherstellung

- `python3 -m lernloop backup` legt `data/backups/lernloop-<Zeit>.sqlite` plus `.sha256` an.
- `python3 -m lernloop restore data/backups/lernloop-<Zeit>.sqlite` prüft Prüfsumme und
  Integrität, sichert den aktuellen Stand vorher als `vor-wiederherstellung-….sqlite` und stellt
  dann wieder her.
- Für eine vollständige Sicherung außerhalb des Laptops den ganzen Ordner `data/` kopieren.

## Tests

```bash
python3 -m unittest discover -s tests -t .
```

## Bekannte Grenzen

Siehe [`docs/01-phase1-planung.md`](docs/01-phase1-planung.md) §12, insbesondere: Ohne
Experimente lernt das System nur, was dokumentiert ist; ein wörtlicher Beleg zeigt, dass die
Quelle etwas sagt, nicht dass es stimmt; Pro-Nutzungslimits bremsen die Geschwindigkeit.
