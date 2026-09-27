# Phase 1: Planung – Make-Lernloop

**Stand:** 27.09.2026 · **Bezug:** Entwicklungsbrief vom 27.09.2026 · **Status:** Vorschlag zur Abnahme

Dieses Dokument liefert die in §15 (Phase 1) geforderten Punkte: Architekturvorschlag,
Hardware- und Modellentscheidung, Kostenannahmen, Datenmodell, Quellenrahmen, ersten
Themenbereich und Prüfverfahren. Alles, was nur der Auftraggeber entscheiden kann, steht
gesammelt in [`02-offene-entscheidungen.md`](02-offene-entscheidungen.md).

Aussagen über Make.com selbst sind in diesem Dokument bewusst **keine Fakten**, sondern
Lernziele und Fragen. Fachliche Aussagen entstehen erst im Lernloop mit Belegen.

---

## 1. Leitprinzipien der Umsetzung

1. **Das Programm steuert, die KI arbeitet zu.** Zustände, Limits, Zugriffe, Statuswechsel
   und Bewertung liegen im Code. Die KI liefert Vorschläge (Suchfragen, Aussagen,
   Antworten) als strukturierte Daten, die das Programm prüft und annimmt oder verwirft.
2. **Kein Status ohne mechanisch prüfbaren Beleg.** Eine Aussage wird nur „dokumentiert“,
   wenn das zitierte Textstück wörtlich im gespeicherten Quelltext vorkommt
   (Programmprüfung, nicht KI-Urteil).
3. **Prüfaufgaben sind technisch unerreichbar** für den Lernpfad – nicht nur „per Prompt
   verboten“.
4. **„Ungeklärt“ ist ein reguläres Ergebnis** und wird wie jedes andere gespeichert.
5. **Einfach zuerst.** Lexikalische Suche (SQLite FTS5/BM25) vor Vektordatenbank; eine
   KI-Instanz vor Multi-Agenten. Ausbau nur nach nachgewiesenem Nutzen (Phase 3).

---

## 2. Architekturvorschlag

### 2.1 Technologie

| Bereich | Wahl | Begründung |
|---|---|---|
| Sprache | Python 3.11+ | Plattformunabhängig (macOS/Windows/Linux), gute Bibliotheken für HTML-Verarbeitung, SQLite eingebaut |
| Speicher | Eine SQLite-Datei (WAL-Modus) + Rohquellen-Ordner | Kein Serverbetrieb, transaktionssicher, einfach zu sichern und zu exportieren |
| Wissensabruf | SQLite FTS5 (BM25), später optional Embeddings | Nachvollziehbar, lokal, kostenlos; Embeddings erst, wenn Abruftests Lücken zeigen |
| Bedienung | Kommandozeile (`lernloop …`) + HTML-Sitzungsbericht | Brief §14: CLI reicht zunächst |
| Modellanbindung | Austauschbare Schnittstelle „ModelClient“ (API oder lokal) | Entscheidung API vs. lokal ist offen (§13) |

### 2.2 Komponenten (entsprechend Brief §5)

```
                 ┌──────────────────── Steuerung (Orchestrator) ────────────────────┐
                 │  Zustandsautomat · Sperre · Limits/Budget · Checkpoints · Stopp  │
                 └──┬──────────┬──────────┬───────────┬───────────┬──────────┬─────┘
                    │          │          │           │           │          │
               Lernplan   Quellenabruf  KI-Verarb.  Wissens-    Prüf-     Bericht
               (Themen,   (Allowlist-   (Model-     speicher/   komponente (CLI/HTML,
               Ziele,     Fetcher,      Client,     -abruf      (Übung +   Export)
               Fragen)    Herkunft)     Schemas)    (SQLite,    Prüfung
                                                    FTS5)       getrennt)
```

| Komponente | Verantwortung | Durchgesetzt durch |
|---|---|---|
| **Lernplan** | Themenkatalog als Baum mit Voraussetzungen, Lernzielen, offenen Fragen | Datenbanktabellen; KI darf Fragen *vorschlagen*, Programm legt an |
| **Quellenabruf** | Holt nur freigegebene öffentliche Seiten, speichert Rohtext, Hash, Metadaten | Allowlist, Netzwerk-Guard (siehe §7), Größen-/Ratenlimits |
| **KI-Verarbeitung** | Suchfragen formulieren, Aussagen mit Zitat extrahieren, Lücken benennen, Aufgaben beantworten | Ausgabe nur als validiertes JSON-Schema; keine Werkzeuge mit Seiteneffekten |
| **Wissensspeicher** | Quellen, Abschnitte, Erkenntnisse, Belege, Konflikte, Prüfungen, Versionen | Statusübergänge nur über Programmfunktionen mit Regeln |
| **Wissensabruf** | Für eine Frage relevante *aktuelle* Erkenntnisse und Quellabschnitte liefern | Filter auf gültige Status; eigene Abruftests (§6.4) |
| **Prüfkomponente** | Übungsaufgaben im Lernloop; zurückgehaltene Prüfaufgaben nur im Eval-Befehl | Verschlüsselte Prüfsammlung, getrennter Befehl, Nur-Lese-DB-Verbindung |
| **Steuerung** | Sitzungsablauf, Wiederaufnahme, Limits, Abbruchgründe | Zustandsautomat, Dateisperre, Budget-Reservierung |
| **Bericht** | Sitzungs- und Vergleichsberichte, Abdeckung je Thema, Verbrauch | Nur aus gespeicherten Daten generiert, keine KI-Zusammenfassung als Kennzahl |

### 2.3 Befehle (geplante CLI)

```
lernloop init                      # Datenbank + Ordnerstruktur anlegen
lernloop plan show|add-topic       # Themenkatalog ansehen/pflegen
lernloop learn --topic T [--resume]# eine Lernsitzung (manuell gestartet)
lernloop ask "Frage"               # Wissensabruf + Antwort mit Belegen (Variante B)
lernloop review                    # Konflikte/Entwürfe zur menschlichen Prüfung
lernloop exam run --variant A|B    # zurückgehaltene Prüfung (Schlüssel nötig)
lernloop report session|coverage|compare
lernloop export | backup | restore
```

### 2.4 Ablauf einer Lernsitzung als Zustandsautomat (Brief §6)

```
GEPLANT → ZIEL_GEWÄHLT → VORWISSEN_GELADEN → FRAGE_FORMULIERT → RECHERCHE
   → AUSSAGEN_ERFASST → ÜBUNG_GEPRÜFT → (FEHLER_KLASSIFIZIERT → NACHARBEIT → ÜBUNG_GEPRÜFT)*
   → FESTGESCHRIEBEN → ABGESCHLOSSEN
```

Abschlussgründe (genau einer pro Sitzung): `ziel_erreicht`, `limit_erreicht`,
`beweislage_fehlt`, `kein_fortschritt`, `abgebrochen_durch_nutzer`, `absturz_erkannt`.

- **Checkpoint nach jedem Zustand** in der Datenbank (Transaktion). `--resume` setzt am
  letzten Checkpoint fort.
- **Kein Fortschritt** = zwei Nacharbeitsrunden in Folge ohne neue belegte Aussage und
  ohne besseres Übungsergebnis → Abbruch. Wiederholtes Lesen nur mit konkretem
  Fehler/Frage als Anlass (Brief §6).
- **Fehlerklassifikation** (Schritt 7): `quellenproblem`, `abrufproblem`,
  `anwendungsfehler`, `beweislage_unzureichend`. Die Nacharbeit richtet sich nach der
  Klasse (z. B. Abrufproblem → Abrufindex/Verschlagwortung, nicht neu recherchieren).
- **Absturzsicherheit:** Neue Erkenntnisse einer Sitzung haben bis `FESTGESCHRIEBEN` den
  Status `entwurf` und gehören zu einer Sitzung. Findet der nächste Start eine Sitzung
  ohne Abschluss, wird sie als `absturz_erkannt` markiert; ihre Entwürfe werden nie
  automatisch hochgestuft.
- **Gleichzeitige Sitzungen:** exklusive Sperrdatei (`lernloop.lock` mit PID und Startzeit)
  plus `BEGIN IMMEDIATE`-Lease in der Datenbank. Eine zweite Sitzung startet nicht.

---

## 3. Datenmodell (Brief §8)

Alle Tabellen in einer SQLite-Datei; Rohquellen zusätzlich als Dateien (`sources/raw/<hash>.html`).
IDs sind stabile, lesbare Kennungen (z. B. `ERK-000123`).

### 3.1 Tabellen

**`topic`** – Themenkatalog
`id, parent_id, title, description, learning_goals (JSON), prerequisites (JSON topic_ids), status (offen|in_arbeit|abgedeckt|ungeklärt)`

**`source`** – eine abgerufene Seite
`id, url, final_url, title, fetched_at, published_or_updated_at (falls sichtbar), version_ref (falls erkennbar), content_hash, raw_path, license_note, source_type (offizielle_doku|community|video …), fetch_status`

**`source_section`** – Abschnitt einer Quelle (Überschrift + Text)
`id, source_id, anchor, heading_path, text, char_start, char_end, content_hash`
→ Grundlage für nachvollziehbare Zitate; bei erneutem Abruf lässt sich über den Hash
erkennen, ob sich ein Abschnitt geändert hat.

**`claim`** – eine Erkenntnis (Brief §8 „Pro Erkenntnis“)

| Feld | Bedeutung |
|---|---|
| `id`, `topic_id` | Eindeutige ID und Thema |
| `statement` | Präzise Aussage |
| `app`, `module`, `module_version` | Soweit bestimmbar, sonst `NULL` (nicht geraten) |
| `scope`, `preconditions` | Gültigkeitsbereich und Voraussetzungen |
| `io_behavior` (JSON) | Eingabe-/Ausgabeverhalten, falls relevant |
| `derivation` | `direkt_zitiert` · `aus_mehreren_abschnitten_gefolgert` · `ki_schlussfolgerung` |
| `status` | siehe 3.2 |
| `status_reason` | Pflichtfeld bei jedem Statuswechsel |
| `last_reviewed_at`, `reviewed_by` | Mensch, Programmregel oder Sitzung |
| `supersedes_id` | Vorgänger (bei Einschränkung, Zusammenführung, Korrektur) |
| `session_id`, `created_at` | Herkunft |

**`evidence`** – Beleg zu einer Erkenntnis
`id, claim_id, section_id, quote, relation (stützt|widerspricht|schränkt_ein), verified_quote (bool)`
→ `verified_quote` setzt ausschließlich das Programm: normalisierter Wörtlich-Abgleich von
`quote` gegen `source_section.text`.

**`conflict`** – offener Widerspruch
`id, claim_ids (JSON), description, status (offen|geklärt|nicht_klärbar), resolution, resolved_at`

**`task`** – Übungs- oder Prüfaufgabe
`id, pool (übung|prüfung|ausgemustert), topic_id, task_type, prompt, expected (JSON), rubric (JSON), expected_source (mensch|experiment|dokumentiert_und_mensch_bestätigt), approved_by, similarity_group`
→ Prüfaufgaben liegen **nicht** in dieser Datenbank im Klartext, sondern verschlüsselt
(siehe §6.2). In der DB steht nur ein Platzhalter mit ID und Hash.

**`attempt`** – ein Lösungsversuch
`id, task_id, session_id|eval_run_id, variant (A|B|lernen), answer, cited_claims, cited_sections, score (JSON je Rubrik-Kriterium), grader (regel|mensch), error_class, created_at`

**`session`** – Lernsitzung
`id, topic_id, goal, state, end_reason, started_at, ended_at, limits_snapshot (JSON), usage (JSON)`

**`usage_event`** – Verbrauch
`id, session_id|eval_run_id, kind (modellaufruf|abruf), model, input_tokens, output_tokens, cached_tokens, cost_estimate_usd, reserved_usd, duration_ms, created_at`

**`eval_run`** – Vergleichslauf
`id, variant, model_id, model_settings, source_access, knowledge_snapshot_hash, task_set_hash, started_at, ended_at, notes`

**`claim_history`** – unveränderliches Änderungsprotokoll (Append-only) für jede Änderung an `claim`.

### 3.2 Status einer Erkenntnis und erlaubte Übergänge

| Status | Bedeutung | Voraussetzung (programmseitig geprüft) |
|---|---|---|
| `entwurf` | Von der KI vorgeschlagen, noch nicht festgeschrieben | – |
| `dokumentiert` | Durch offizielle Doku wörtlich belegt | ≥ 1 Beleg mit `verified_quote = true`, Relation `stützt`, keine offene widersprechende Evidenz |
| `theoretisch_geprüft` | Zusätzlich in Übungsaufgaben mit fachlich bestätigter Lösung korrekt angewendet | `dokumentiert` + ≥ 1 bestandene Übung mit Mustlösung von Mensch/Experiment |
| `praktisch_bestätigt` | Durch kontrolliertes Experiment bestätigt | **In Version 1 gesperrt** (Brief §10) |
| `widersprüchlich` | Belege widersprechen sich | offener `conflict` |
| `veraltet` | Quelle geändert/abgelöst | Abschnitts-Hash geändert oder Ablösung belegt |
| `zurückgezogen` | Widerlegt oder durch Nachfolger ersetzt | `status_reason` + ggf. `supersedes` |
| `ungeklärt` | Frage gestellt, Beweislage reicht nicht | – |

Regeln:
- `ki_schlussfolgerung` kann höchstens `entwurf` oder `ungeklärt` sein, bis ein Mensch sie
  bestätigt oder ein Beleg sie wörtlich stützt.
- Keine Selbsteinschätzung („95 % sicher“) als Feld – Unsicherheit ergibt sich aus Status,
  Belegen und Konflikten.
- Wissensabruf liefert standardmäßig nur `dokumentiert`, `theoretisch_geprüft`,
  `widersprüchlich` (mit Warnhinweis) und `ungeklärt` (als Hinweis „offen“) –
  nie `zurückgezogen`/`veraltet` als aktuelle Wahrheit.
- **Pflege:** Zusammenführen (Duplikate → neue Erkenntnis mit `supersedes`),
  Einschränken (überbreite Aussage → engere Nachfolger-Aussage), Zurückziehen. Alte
  Fassungen bleiben in `claim_history` nachvollziehbar.
- **Duplikaterkennung:** normalisierte Textähnlichkeit + gleiche Belegabschnitte →
  Vorschlag zur Zusammenführung, nicht automatische Zusammenführung.

---

## 4. Quellenrahmen (Brief §7)

### 4.1 Version 1: nur offizielle öffentliche Dokumentation

Vorgeschlagene Allowlist (vor Phase 2 zu verifizieren, siehe Entscheidung E5):

| Host | Zweck |
|---|---|
| `help.make.com` | Hilfe-Center / Benutzerdokumentation |
| `developers.make.com` | Entwicklerdokumentation (Custom Apps, API) |
| `www.make.com` (nur explizit freigegebene Pfade, z. B. Preis-/Tarifseiten) | Tarife und Grenzen, soweit relevant |

Vor dem ersten Abruf prüft das Programm **und** dokumentiert ein Mensch:
- `robots.txt` der Hosts (wird technisch respektiert),
- Nutzungsbedingungen hinsichtlich automatisiertem Abruf und lokaler Speicherung,
- ob es eine offizielle strukturierte Quelle gibt (Sitemap, Export, API), die dem
  Scraping vorzuziehen ist.

Falls die Bedingungen das lokale Speichern ganzer Seiten nicht erlauben, speichert das
System nur Abschnitts-Hashes, kurze Zitate und die URL und ruft bei Bedarf erneut ab.

### 4.2 Metadaten je Quelle

URL (angefragt + final), Titel, Abrufzeit, sichtbares Veröffentlichungs-/Aktualisierungs-
datum (nur wenn auf der Seite vorhanden, sonst `NULL`), Versionsbezug (z. B. Modulversion,
falls genannt), Inhalts-Hash, Quelltyp.

### 4.3 Gewichtung

- Offizielle Doku hat Vorrang, gilt aber nicht als fehlerfrei; Widersprüche innerhalb der
  Doku werden als `conflict` geführt.
- KI-Zusammenfassungen sind keine Quelle; `derivation = ki_schlussfolgerung` zählt nie
  als Beleg.
- Spätere Communityquellen erhalten den Typ `community` und können allein höchstens
  „Hinweis mit Voraussetzungen“ begründen. Mehrere Beiträge mit gleichem Wortlaut/Ursprung
  werden als ein Beleg gezählt (Ähnlichkeitsgruppe).

---

## 5. Erster Themenbereich (Pilot)

### Vorschlag: „Datenfluss zwischen Modulen – Bundles, Iteration und Aggregation“

Begründung:
- Zentral für fast jedes Szenario und eine häufige Fehlerquelle in der Praxis.
- Gut geeignet für **Vorhersageaufgaben** (Wie viele Bundles/Ausführungen entstehen? Was
  steht im Ergebnis?), deren Soll-Ergebnis ein Make-kundiger Mensch oder später ein
  Experiment eindeutig bestätigen kann.
- Kommt ohne Fremddienste aus; im Wesentlichen durch offizielle Doku abgedeckt.
- Klar abgrenzbar, aber mit echten Abhängigkeiten (Datentypen, Mapping, Funktionen).

### Lernziele (Fragen, noch keine Antworten)

1. Was ist ein Bundle, und wie verarbeiten nachfolgende Module mehrere Bundles?
2. Wie arbeiten Iterator und die Aggregator-Module (Array, Text, numerisch, Tabelle)
   zusammen? Welche Einstellungen (z. B. Quellmodul, Gruppierung) gibt es und was bewirken sie?
3. Was passiert bei leeren Arrays, fehlenden Feldern, einem statt mehreren Treffern?
4. Wie werden Arrays und Collections gemappt (Indexierung, eingebaute Array-Funktionen)?
5. Wie wirken sich Iteration und Aggregation auf Verbrauch (Operationen/Credits) aus?
6. Welche Anleitungen dazu sind veraltet oder widersprüchlich?

### Abgrenzung (nicht im Pilot)

HTTP/Webhooks, Fehler-Handler, Datenspeicher, Zeitsteuerung, einzelne Fremd-Apps.

### Umfang der Pilot-Aufgaben

- ca. 30 Übungsaufgaben (dürfen zum Lernen genutzt werden)
- ca. 40 zurückgehaltene Prüfaufgaben (für Phase 3; siehe §6 und Entscheidung E1)
- ca. 20 Abruftestfragen (Frage → erwartete Erkenntnis/Quellabschnitt)

---

## 6. Prüfverfahren (Brief §9, §11)

### 6.1 Aufgabentypen (mit maschinenlesbarer Bewertung)

| Typ | Beispiel | Bewertung |
|---|---|---|
| Vorhersage | „Szenario X liefert 3 Bundles in Modul 2 – wie viele Bundles gibt Modul 4 aus?“ | Exakter Wert + Begründungspunkte |
| Mapping-Fehler | „Warum ist dieses Mapping falsch?“ | Rubrik: richtiges Problem erkannt, richtige Begründung |
| Randfall | Leeres Feld / mehrere Treffer | Rubrik |
| Voraussetzungen | „Was braucht Kombination A→B?“ | Checkliste |
| Widersprüche | „Welche der zwei Anleitungen gilt heute?“ | Rubrik + Belegpflicht |
| Unbeantwortbar | Frage ohne belastbare Quelle | Punkt nur für korrektes „offen“ |

Jede Rubrik wird **vor** der Nutzung festgelegt und versioniert. Jede Antwort wird zusätzlich
bewertet auf: unbelegte Aussagen, fälschliche Gewissheit, berechtigtes/unnötiges Offenlassen,
Tragfähigkeit der Belege (Zitat existiert und stützt die Aussage tatsächlich).

### 6.2 Trennung Übung / Prüfung – technisch durchgesetzt

- Prüfaufgaben und Musterlösungen liegen in `exam/exam.enc`, verschlüsselt mit einem
  Schlüssel, den **nur** der Befehl `lernloop exam run` zur Laufzeit abfragt (Passphrase).
  Der Lernpfad hat keinen Code zum Entschlüsseln.
- Während `exam run` öffnet das Programm den Wissensspeicher **nur lesend**
  (`mode=ro`); Antworten landen ausschließlich in `eval_run`/`attempt`.
- Beim Anlegen jeder Aufgabe prüft das Programm die Ähnlichkeit gegen die jeweils andere
  Sammlung (normalisierte n-Gramm-Ähnlichkeit); Treffer über Schwellenwert müssen ein
  Mensch freigeben oder werden abgewiesen.
- Wird eine Prüfaufgabe später als Lernmaterial genutzt, wechselt sie nach
  `ausgemustert` und das Programm verlangt Ersatz, bevor der nächste Vergleich zählt.
- Einschränkung (ehrlich benannt): Die KI kennt ggf. ähnliche Fragen aus ihrem Training;
  das lässt sich nicht ausschließen, betrifft aber A und B gleich.

### 6.3 Wer bestätigt Musterlösungen?

Siehe Entscheidung **E1**. Ohne bestätigte Musterlösung wird eine Aufgabe als
`nicht_bewertbar` geführt und fließt in kein Erfolgsurteil ein. Ein zweites KI-Modell darf
nur als Hinweisgeber für die menschliche Prüfung dienen.

### 6.4 Abruftests (getrennt, Brief §8)

Für ~20 Fragen ist festgelegt, welche Erkenntnis/welcher Abschnitt gefunden werden muss.
Gemessen: Treffer unter den ersten k Ergebnissen (Recall@5) und Rang. Fehlschläge werden als
`abrufproblem` klassifiziert und gezielt nachgearbeitet (Synonyme, Verschlagwortung).

### 6.5 Vergleich A vs. B (Phase 3)

| | A | B |
|---|---|---|
| Modell, Einstellungen | identisch | identisch |
| Dokumentationssuche | gleiche Allowlist, gleiche Abrufwerkzeuge, gleiches Abruflimit | identisch |
| Lernspeicher | – | Nur-Lese-Zugriff |
| Aufgaben | dieselben zurückgehaltenen Prüfaufgaben | identisch |
| Budget je Aufgabe | identisch | identisch |

- Jede Variante mindestens **3 Durchläufe** pro Aufgabe, um Schwankung sichtbar zu machen.
- Bewertung durch Rubrik; Regeln automatisch, alles Weitere durch den festgelegten Prüfer,
  **blind** (ohne Wissen, ob A oder B).
- Kosten: B wird mit einmaligen Lernkosten + laufender Pflege + Antwortkosten ausgewiesen.
- **Früher Zwischentest:** Nach etwa 10 Lernsitzungen treten A und B auf 10–15 zurückgehaltenen
  Aufgaben gegeneinander an. Das Ergebnis ist ausdrücklich vorläufig und dient nur dazu, früh zu
  sehen, ob der Speicher sich überhaupt bemerkbar macht. Ohne sichtbaren Unterschied wird zuerst
  die Ursache untersucht (Quellen, Abruf, Anwendung), bevor weitergelernt wird.
- Erfolgskriterium wird **vor** dem Lauf festgelegt (Entscheidung E4) und im Bericht mit
  Datum zitiert. Stichproben < 100 Aufgaben werden als „vorläufig“ gekennzeichnet.

---

## 7. Sicherheit und Zugriffsbeschränkungen (Brief §12)

Technische Umsetzung, nicht nur Prompt:

| Anforderung | Umsetzung |
|---|---|
| Nur freigegebene Ziele | HTTP-Client mit Host-Allowlist; nur `https`; Weiterleitungen werden einzeln gegen die Allowlist geprüft (max. 3) |
| Kein Zugriff auf lokale/interne Dienste | Aufgelöste IP wird vor Verbindung geprüft: keine privaten, Loopback-, Link-Local- oder Metadaten-Adressen; Verbindung erfolgt auf die geprüfte IP (Schutz vor DNS-Rebinding) |
| Fremde Inhalte = Daten | KI erhält Quelltext nur als markierte Daten; die KI hat **keine** Werkzeuge mit Seiteneffekten. Alles, was sie „will“ (URL abrufen, Aussage speichern), ist ein Vorschlag, den das Programm gegen Regeln prüft |
| Keine Befehle aus Quellen | Kein Shell-/Code-Ausführungswerkzeug; heruntergeladene Inhalte werden nie ausgeführt, nur Text extrahiert (HTML → Text, keine Skripte) |
| Größen-/Typlimits | Nur `text/html`; max. Seitengröße (z. B. 2 MB); Timeout |
| Dateizugriff | Alle Pfade werden auf das Projektverzeichnis normalisiert und geprüft |
| Geheimnisse | API-Schlüssel nur aus Umgebungsvariable oder Betriebssystem-Schlüsselbund; nie in DB, Protokoll oder Prompt; Protokolle filtern bekannte Schlüsselformate |
| Kein Browserprofil, kein Postfach, keine Make-Konten, keine Posts, keine Käufe | Schlicht nicht implementiert; Allowlist enthält keine Schreib-Endpunkte; HTTP-Client erlaubt nur `GET` |
| Was verlässt den Laptop (bei API) | Nur: Systemanweisung, Frage/Lernziel, Auszüge aus öffentlicher Doku, gespeicherte Erkenntnisse. Keine Dateien außerhalb des Projekts, keine Geheimnisse. Wird in der Doku zum Setup aufgeführt |

---

## 8. Hardware- und Modellentscheidung (Brief §13)

### 8.1 Hardware

Noch unbekannt → `scripts/hardware_check.py` liefert Betriebssystem, Chip, RAM, freien
Speicher und GPU-Hinweise. Richtwerte:

| Option | Mindestens sinnvoll |
|---|---|
| Nur Steuerung + Speicher (Modell per API) | beliebiger aktueller Laptop, ~2 GB freier Speicher |
| Lokales Modell ~7–8 B Parameter (quantisiert) | 16 GB RAM, ~10 GB frei |
| Lokales Modell ~14 B | 32 GB RAM (oder Apple Silicon mit 24–32 GB), ~20 GB frei |
| Lokales Modell ≥ 30 B | 48–64 GB RAM / leistungsfähige GPU |

### 8.2 Modell: Empfehlung

**Zwei Anbindungen hinter einer gemeinsamen Schnittstelle `ModelClient`.** Vorhanden sind
ein Claude-Pro-Abo und ein Claude-API-Zugang.

| Anbindung | Wie | Einsatz |
|---|---|---|
| `claude_code` (Pro-Abo) | Programm ruft lokal `claude -p` auf, mit dem Pro-Abo angemeldet | **Start: Entwicklung, Tests, Lernsitzungen (Phase 2)** – allein ausreichend |
| `anthropic_api` (API) | Offizielles Python-SDK `anthropic`, eigener Projektschlüssel | **Optional ab Phase 3** – Entscheidung erst dann, anhand der in Phase 2 gemessenen Werte |

**Festlegung für den Start: nur das Pro-Abo.** Bis einschließlich Phase 2 fallen keine
Kosten über das Abo hinaus an; die API-Anbindung wird gebaut, bleibt aber ausgeschaltet.

Abwägung für Phase 3 (dann zu entscheiden):
- **Lernen über Pro:** Es entstehen keine zusätzlichen Kosten. Die Nutzungslimits des Abos
  (Kontingente je 5-Stunden-Fenster und je Woche) bremsen, aber Lernsitzungen sind ohnehin
  manuell gestartet und wiederaufnehmbar.
- **Vergleich über Pro ist möglich:** A und B nutzen dasselbe Modell, das reicht für die
  Fairness. Das Programm wechselt A und B je Aufgabe ab, damit eine Unterbrechung durch ein
  Nutzungslimit beide Varianten gleich trifft, und setzt nach der Pause fort. Nachteil: Der
  Lauf dauert Tage, und Modelländerungen im Abo während des Laufs sind nicht ausgeschlossen.
- **Vergleich über API wäre sauberer:** Modellversion und Einstellungen lassen sich exakt festlegen, der
  Verbrauch wird je Aufruf genau gemeldet, und die Batch-Verarbeitung (50 % günstiger) passt
  zu den Vergleichsläufen. Die ~720 Vergleichsaufrufe würden das Pro-Kontingent über Tage
  belegen, und ein Abbruch mitten im Lauf durch ein Nutzungslimit würde den Vergleich stören.
- Das Modell, mit dem gelernt wird, darf sich vom Antwortmodell im Vergleich unterscheiden:
  Der Lernspeicher besteht aus Daten mit Belegen, nicht aus Modellgewichten. Für die
  Hypothese entscheidend ist nur, dass **A und B dasselbe Modell** nutzen.

Auflagen für `claude_code` (programmseitig gesetzt):
- **Alle Werkzeuge von Claude Code abgeschaltet** (kein Dateizugriff, keine Befehle, kein
  Webabruf). Claude verarbeitet nur den übergebenen Text; Abruf und Speicherung macht das
  Programm (Brief §12).
- Modell je Aufruf fest angegeben; Ausgabe als JSON inklusive Token-Verbrauch.
- Aufruf in einem leeren Arbeitsverzeichnis ohne Projektdateien.
- Meldet Claude Code ein erreichtes Nutzungslimit, endet der Schritt sauber; die Sitzung
  pausiert mit Checkpoint und wird mit `--resume` fortgesetzt.
- Vor dem Start zu prüfen: welche Modelle im Pro-Abo für Claude Code verfügbar sind, und
  die aktuellen Nutzungsbedingungen für die automatisierte persönliche Nutzung. Das Abo ist
  für die persönliche Nutzung gedacht; für ein Produkt, das andere nutzen, wäre die API nötig.
- Datenschutz: Beim Abo gelten die Datenschutzeinstellungen des Kontos. Gesendet werden nur
  öffentliche Doku-Auszüge und daraus abgeleitetes Wissen.

Auflagen für `anthropic_api`:
- Eigener API-Schlüssel nur für dieses Projekt, zusätzlich ein Ausgabenlimit in der
  Anthropic Console als zweite Sicherung.
- Programmseitige Budget-Reservierung vor jedem Aufruf (siehe §9).

Modelle und Preise für die API (Preise laut Anbieterübersicht, Stand Juni 2026 – vor
Aktivierung auf der aktuellen Preisseite prüfen):

| Modell | Eingabe $/1 Mio. Tokens | Ausgabe $/1 Mio. Tokens | Rolle |
|---|---|---|---|
| Claude Opus 5 (`claude-opus-5`) | 5,00 | 25,00 | Empfohlen für den Vergleich (Qualität) |
| Claude Sonnet 5 (`claude-sonnet-5`) | 2,00 | 10,00 | Günstigere Alternative |
| Claude Haiku 4.5 (`claude-haiku-4-5`) | 1,00 | 5,00 | Nur für Hilfsaufgaben (z. B. Suchbegriffe) |

**Ohne bestätigtes API-Budget (Entscheidung E2, frühestens vor Phase 3) werden keine API-Aufrufe aktiviert.**
Standard der Beispielkonfiguration: `paid_calls_enabled = false`, Anbindung `claude_code`.

---

## 9. Kostenannahmen

Grobe Schätzung, um Größenordnungen zu klären – keine Zusage. Annahme je Modellaufruf:
~15.000 Eingabe-Tokens (Doku-Auszüge + Kontext) und ~2.000 Ausgabe-Tokens.

Kosten je API-Aufruf: Opus 5 = 15.000/1 Mio. × 5 $ + 2.000/1 Mio. × 25 $ ≈ **0,125 $**;
Sonnet 5 = 15.000/1 Mio. × 2 $ + 2.000/1 Mio. × 10 $ = **0,05 $**.

| Posten | Menge | Anbindung | Zusätzliche Kosten |
|---|---|---|---|
| Lernen (Phase 2) | ~30 Sitzungen × ~20 Aufrufe = ~600 Aufrufe | Pro-Abo | **0 $** (verbraucht Pro-Kontingent) |
| Vergleich A+B (Phase 3) | 40 Aufgaben × 2 Varianten × 3 Läufe × ~3 Aufrufe = 720 Aufrufe | Pro-Abo **oder** API | Pro: **0 $**; API (Batch): Opus 5 ~45 $, Sonnet 5 ~18 $ (720 × 0,125 $ bzw. × 0,05 $, halbiert) |
| **Summe zusätzlich zum Abo bis Ende Phase 2** | | | **0 $** |
| Optional Phase 3 über API inkl. ~15 $ Reserve | | | ~60 $ (Opus 5) bzw. ~35 $ (Sonnet 5) |

- Zum Vergleich ohne Pro-Abo (alles über API): ~165 $ (Opus 5) bzw. ~66 $ (Sonnet 5).
- Unsicherheit: Faktor 2 in beide Richtungen. Die ersten 3 Lernsitzungen dienen als Messung;
  danach wird die Schätzung mit echten Werten aktualisiert und vorgelegt.
- **Zeit statt Geld beim Pro-Abo:** ~600 Aufrufe à ~17.000 Tokens verteilen sich
  voraussichtlich auf mehrere Tage bis Wochen, weil das Kontingent auch für die sonstige
  Nutzung von Claude reicht. Das Programm begrenzt dafür Aufrufe und Tokens je Sitzung und
  je Tag (siehe `config/limits.example.toml`), damit genug Kontingent für dich übrig bleibt.
- Menschliche Prüfzeit ist der größere Kostenfaktor: ~70 Musterlösungen à ~5–10 Min.
  ≈ 6–12 Stunden Fachprüfung.

Durchsetzung bei der API: Vor jedem Aufruf wird der maximal mögliche Betrag (gezählte
Eingabe-Tokens × Preis + `max_tokens` × Ausgabepreis) gegen das Restbudget **reserviert**;
nach der Antwort wird mit dem tatsächlichen Verbrauch abgeglichen. Ist die Reservierung
nicht möglich, stoppt die Sitzung mit `limit_erreicht`. Beim Pro-Abo werden stattdessen
Aufrufe und gemeldete Tokens gezählt.

---

## 10. Berichte (Brief §14)

Sitzungsbericht (CLI-Ausgabe + HTML-Datei): Lernziel, bearbeitete Quellen (URL, Abrufzeit),
neue/geänderte Erkenntnisse mit Status und Belegen, Übungsergebnisse, offene Widersprüche,
Verbrauch (Tokens, Kosten, Abrufe), Dauer, Abschlussgrund.

Abdeckungsbericht: je Thema im benannten Katalog Anzahl Lernziele mit Status
`abgedeckt`/`ungeklärt`/`offen`, Anzahl Erkenntnisse je Status, Konflikte. **Keine**
Gesamtprozentzahl „Make verstanden“.

Export: gesamte DB als JSON Lines je Tabelle + Rohquellen; Sicherung = Kopie über SQLite
Backup-API (konsistent auch während Nutzung); Wiederherstellung mit Prüfsummen-Check.

---

## 11. Plan für Phase 2 (nach Abnahme)

| Schritt | Ergebnis | Abnahmekriterium |
|---|---|---|
| 1 | Grundgerüst: CLI, DB-Schema, Sperre, Limits, Budget-Reservierung | Tests: zweite Sitzung wird abgewiesen; Limit stoppt nachweislich |
| 2 | Sicherer Fetcher + Quellen/Abschnitte | Tests: Nicht-Allowlist, private IP, Weiterleitung nach außen werden abgewiesen |
| 3 | ModelClient + JSON-Schemas + Zitatprüfung | Test: erfundenes Zitat → Erkenntnis bleibt `entwurf` |
| 4 | Lernsitzung als Zustandsautomat mit Checkpoints | Test: Abbruch mitten in der Sitzung → Wiederaufnahme, keine Entwürfe als geprüft |
| 5 | Abruf (FTS5) + Abruftests | Recall@5 wird berichtet |
| 6 | Übungen, Fehlerklassifikation, gezielte Nacharbeit | Sitzungsbericht zeigt Fehlerklasse und Nacharbeit |
| 7 | Verschlüsselte Prüfsammlung, Ähnlichkeitsprüfung | Test: Lernpfad kann Prüfaufgaben nicht lesen |
| 8 | Berichte, Export, Backup/Restore | Wiederherstellung aus Backup reproduziert identische Prüfsummen |
| 9 | Pilotdurchlauf auf dem ersten Themenbereich | Sitzungsberichte, offene Punkte, gemessene Kosten |

**Umsetzungsstand (27.09.2026):** Schritte 1–6 und 8 sind in Version 0.1 umgesetzt (siehe
`README.md`); Schritt 7 (verschlüsselte Prüfsammlung) folgt mit Phase 3. Schritt 9 (Pilotdurchlauf)
startet auf dem Laptop des Auftraggebers.

### Nutzungsschicht (nach Phase 2)

Damit das erarbeitete Wissen später auch beim Arbeiten mit Claude an Make-Szenarien verfügbar ist:
- **Export für Claude-Projekte:** aktuelle Erkenntnisse mit Status und Belegen als Markdown.
- **MCP-Schnittstelle (nur lesend):** Claude Code bzw. Claude Desktop kann den Wissensspeicher
  gezielt abfragen und sieht dabei den Status (belegt, widersprüchlich, offen).
Beide geben nichts Zurückgezogenes oder Veraltetes als aktuell aus und können nichts verändern.

---

## 12. Bekannte Grenzen

- Keine praktische Bestätigung in Version 1 → höchster erreichbarer Status ist
  `theoretisch_geprüft`.
- Wörtliche Zitatprüfung beweist, dass die Quelle es *sagt*, nicht, dass es *stimmt*.
- Die Aussagekraft von Phase 3 hängt an Anzahl und Qualität der fachlich bestätigten
  Prüfaufgaben; 40 Aufgaben ergeben nur ein vorläufiges Ergebnis.
- Kontamination durch Trainingswissen des Modells ist nicht ausschließbar (betrifft A und B gleich).
- Dokumentationsseiten können sich zwischen Lernen und Prüfung ändern → Abrufzeitpunkte
  und Hashes werden in jedem Vergleichslauf festgehalten.
- **Betrieb nur über das Pro-Abo (Start):**
  - Nutzungslimits (je 5-Stunden-Fenster und je Woche) werden mit deiner sonstigen Claude-Nutzung
    geteilt; das Restkontingent ist vorab nicht abfragbar, daher pausiert das Programm erst,
    wenn das Limit gemeldet wird.
  - Welche Modelle im Pro-Abo in Claude Code verfügbar sind, ist vor dem Start zu prüfen.
    Modell-Kurznamen können auf neuere Versionen umgestellt werden; jeder Aufruf protokolliert
    daher die tatsächlich gemeldete Modellversion.
  - Weniger Steuerung als bei der API: Claude Code bringt einen eigenen Systemprompt mit; kein
    Batch, keine direkte Cache-Steuerung, keine erzwungenen Ausgabeschemas. Das Programm prüft
    jede JSON-Antwort selbst und wiederholt bei ungültiger Ausgabe begrenzt.
  - Aufrufe laufen nacheinander; jeder startet einen Claude-Code-Prozess (einige Sekunden
    Zusatzaufwand).
