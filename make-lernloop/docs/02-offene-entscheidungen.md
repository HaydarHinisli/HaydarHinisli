# Offene Entscheidungen vor Phase 2

Diese Punkte kann nur der Auftraggeber entscheiden (Brief §9, §13, §15). Zu jedem gibt es
eine Empfehlung; „Empfehlung übernehmen“ ist eine gültige Antwort.

| Nr. | Entscheidung | Empfehlung | Antwort |
|---|---|---|---|
| E1 | Wer bestätigt Musterlösungen fachlich? | siehe unten | |
| E2 | Budget (Start: nur Pro-Abo, API erst vor Phase 3) | siehe unten | |
| E3 | Modell: Abo, API oder lokal? | siehe unten | |
| E4 | Erfolgskriterium für Phase 3 (vorab festgelegt) | siehe unten | |
| E5 | Quellenrahmen und Nutzungsbedingungen | siehe unten | |
| E6 | Erster Themenbereich | siehe unten | |
| E7 | Ressourcenlimits je Sitzung | siehe unten | |

---

### E1 – Fachliche Verantwortung für Musterlösungen

Optionen:
- **a)** Du selbst (sofern Make-kundig) prüfst jede Musterlösung.
- **b)** Eine externe Make-kundige Person (Freelancer, Make-Partner) prüft gegen Honorar.
- **c)** Kontrollierte Experimente in einem separaten Test-Account – laut Brief erst in einer
  späteren Phase vorgesehen.

**Empfehlung:** a) oder b) für den Pilot. Aufwand ca. 6–12 Stunden für ~70 Aufgaben
(30 Übung, 40 Prüfung). Das System erzeugt Aufgabenentwürfe mit Quellenbelegen; der Prüfer
bestätigt, korrigiert oder verwirft. Ohne E1 kann Phase 3 kein Erfolgsurteil liefern.

### E2 – Budget

Ausgangslage: Pro-Abo (pauschal) und API-Zugang (nach Verbrauch) sind vorhanden.

**Festgelegt für den Start:** Nur das **Pro-Abo** – bis einschließlich Phase 2 keine
zusätzlichen Kosten, API-Aufrufe ausgeschaltet. Tageslimit im Programm: höchstens 60 Aufrufe
pro Tag, damit genug Kontingent für deine sonstige Nutzung bleibt (anpassbar).

**Erst vor Phase 3 zu entscheiden:** Vergleich weiter über das Abo (0 $, dauert Tage) oder über
die API (sauberer und schneller; geschätzt ~60 $ mit Opus 5 bzw. ~35 $ mit Sonnet 5). Grundlage
sind dann die in Phase 2 gemessenen Werte statt Schätzungen (`01-phase1-planung.md` §9). Falls
API: eigener Projektschlüssel mit Ausgabenlimit in der Anthropic Console.

### E3 – Modell

**Empfehlung:** Pro-Abo über Claude Code, mit dem stärksten Modell, das dein Abo in Claude Code
anbietet (vor dem Start prüfen). Ein lokales Modell bleibt eine spätere Option; endgültig
erst nach der Ausgabe von `scripts/hardware_check.py`.

### E4 – Erfolgskriterium (muss vor Phase 3 feststehen)

**Empfehlungsvorschlag:** Der Ausbau (Phase 4) ist gerechtfertigt, wenn Variante B auf den
zurückgehaltenen Prüfaufgaben
1. im Mittel über 3 Läufe mindestens **10 Prozentpunkte** mehr Rubrikpunkte erreicht als A, **und**
2. die Rate fälschlicher Gewissheit (falsche Antwort ohne Kennzeichnung als unsicher/offen)
   **nicht höher** ist als bei A, **und**
3. die Gesamtkosten je richtig beantworteter Aufgabe – inklusive anteiliger Lernkosten über
   angenommene 200 künftige Fragen – höchstens **doppelt so hoch** sind wie bei A.

Alternativ gilt B als Erfolg, wenn es **gleich gut** ist, aber mindestens 30 % weniger
laufende Kosten oder Zeit je Antwort braucht. Bei weniger als 100 Aufgaben wird das
Ergebnis als vorläufig gekennzeichnet.

### E5 – Quellenrahmen

**Empfehlung:** Version 1 nur `help.make.com`, `developers.make.com` und explizit
freigegebene Pfade auf `www.make.com`. Vor dem ersten Abruf werden robots.txt und die
Nutzungsbedingungen geprüft und das Ergebnis dokumentiert; bei Einschränkungen speichert
das System nur Zitate, Hashes und URLs statt ganzer Seiten.

### E6 – Erster Themenbereich

**Empfehlung:** „Datenfluss zwischen Modulen – Bundles, Iteration und Aggregation“
(Begründung in `01-phase1-planung.md` §5). Alternativen: „Filter und Router“,
„Fehlerbehandlung“.

### E7 – Ressourcenlimits je Sitzung

**Empfehlung** (in `config/limits.example.toml` hinterlegt, vom Programm durchgesetzt):

| Limit | Wert |
|---|---|
| Laufzeit je Sitzung | 30 Min. |
| Modellaufrufe je Sitzung | 25 |
| Aufrufe pro Tag (Pro-Kontingent) | 60 |
| Seitenabrufe je Sitzung | 40 |
| Abrufrate | max. 1 Seite / 2 s je Host |
| Nacharbeitsrunden ohne Fortschritt | 2 |
| API-Budget | 0 $ bis Entscheidung vor Phase 3 (E2) |
