# Verkaufsagent – Crazyslip, Creamsi, Panty.com & ähnliche Marktplätze

Der Agent stellt deine Produkte selbstständig auf Marktplätzen wie **Crazyslip**, **Creamsi** und **Panty.com** ein. Für jedes Angebot schreibt er Titel und Beschreibung (Pflicht, immer vorhanden) und pflegt danach die Preise: Er hält sich an deinen Preis und reduziert höchstens um 30 %, und zwar nur, wenn es wirklich angemessen ist.

Weitere Seiten lassen sich ohne Programmierung ergänzen (siehe [Weitere Marktplätze](#weitere-marktplätze)).

## Schnellstart auf dem Mac (ohne Terminal-Befehle)

Im Ordner `verkaufsagent` liegen vier Dateien zum Doppelklicken:

| Datei | Wofür | Wie oft |
|---|---|---|
| `1 - Installieren` | installiert alles | einmal |
| `2 - Plattform einrichten` | bringt dem Agenten das Formular einer Plattform bei | einmal pro Plattform |
| `3 - Produkte bearbeiten` | öffnet Produktliste und Foto-Ordner | bei neuen Produkten |
| `4 - Agent starten` | startet den Agenten | nach jedem Neustart des Macs |
| `5 - Automatisch anmelden einrichten` | Agent meldet sich selbst an (Passwort im Mac-Schlüsselbund) | einmal pro Plattform |
| `6 - Aktualisieren` | holt die neueste Version in denselben Ordner | bei Updates |

Beim ersten Öffnen einer Datei meldet der Mac eventuell „nicht verifizierter Entwickler“. Dann **Rechtsklick → Öffnen → Öffnen**. Das ist nur einmal pro Datei nötig.

## So arbeitet der Agent

| Schritt | Was passiert |
|---|---|
| **Einrichten (einmalig)** | Die Seiten haben keine offizielle Schnittstelle. Deshalb bringst du dem Agenten das Angebotsformular einmal bei: Er öffnet es im Browser, und du klickst nacheinander auf die Felder, die er nennt (Fotos, Titel, Beschreibung, Preis, Kategorie, Tragedauer …). Deine Klicks werden dabei abgefangen, es wird nichts abgeschickt. |
| **Beschreiben** | Claude sieht sich deine Fotos und Angaben an und schreibt pro Plattform Titel und Beschreibung: persönlich, aber dezent und nie explizit. Hinweise aus `notizen` werden **immer** genannt, nichts wird erfunden. Ohne API-Schlüssel oder bei einem Fehler nimmt der Agent eine vollständige Textvorlage. **Ohne gültige Beschreibung wird nie eingestellt.** |
| **Einstellen** | Ein echter Browser füllt das Formular aus, schickt es ab und merkt sich die Angebots-Nummer. Kein Produkt wird doppelt eingestellt. |
| **Preis** | Eingestellt wird **immer exakt zu deinem Preis**. |
| **Preispflege** | Der Preis wird nur reduziert, wenn **alle** Bedingungen erfüllt sind: mindestens 14 Tage online, mindestens 7 Tage seit der letzten Senkung, schwache Nachfrage (wenige Aufrufe, keine Merker). Bei hohem Interesse wird **nie** gesenkt. Ohne Aufrufzahlen wird höchstens um 15 % gesenkt. |
| **Harte Grenze** | Der Preis fällt nie mehr als 30 % unter deinen Preis und nie unter einen gesetzten `mindestpreis`. Diese Grenze ist fest im Code verankert (`MAX_RABATT_ABSOLUT`). Mit `verhandelbar: false` wird der Preis nie gesenkt. |
| **Angebote** | `angebot <produkt> <betrag>` sagt dir, ob du ein Käuferangebot annehmen solltest oder welches Gegenangebot passt. Es liegt nie unter der Untergrenze. |
| **Verkauft** | Verkaufte oder gelöschte Angebote werden erkannt und nicht mehr angefasst. |

Beispiel für 25 € ohne Mindestpreis bei schwacher Nachfrage: 25 → 23 (Tag 14) → 22 (Tag 21) → 21 → 20 → 18 €, danach keine weitere Senkung (Untergrenze 17,50 € = −30 %).

## Installation (auf deinem eigenen Rechner)

```bash
cd verkaufsagent
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
cp config.example.yaml config.yaml
cp produkte.example.yaml produkte.yaml
export ANTHROPIC_API_KEY=sk-ant-...                    # für KI-Beschreibungen (optional)
```

Einen API-Schlüssel der Marktplätze brauchst du nicht, es reicht dein normales Verkäuferkonto.

## Einrichtung (einmal pro Plattform)

```bash
python -m verkaufsagent einrichten crazyslip
python -m verkaufsagent einrichten creamsi
python -m verkaufsagent einrichten panty
```

Der Assistent führt dich durch diese Schritte:

1. **Anmelden** und die Seite **„Neues Angebot erstellen“** öffnen, dann Enter.
2. **Felder anklicken:** Für jedes genannte Feld klickst du im Browser darauf und drückst dann im Terminal Enter. Das Feld wird rosa umrandet, wenn es erkannt wurde. Nur Enter ohne Klick überspringt ein optionales Feld.
3. **Zusatzfelder** wie `tragedauer` oder `versandart` kannst du mit Namen anlernen. Den Wert gibst du dann pro Produkt in `produkte.yaml` unter `felder:` an.
4. **Veröffentlichen-Knopf** anklicken. Er wird nicht ausgelöst.
5. *Optional, empfohlen:* ein bestehendes Angebot öffnen und auf die Anzahl der Aufrufe und Merker klicken (für die Preispflege). Dann den Text angeben, der bei verkauften Angeboten erscheint.
6. *Optional, empfohlen:* die **Bearbeiten-Seite** eines Angebots öffnen und den Speichern-Knopf anklicken. **Ohne diesen Schritt kann der Agent keine Preise ändern.**

Mit `python -m verkaufsagent plattformen` siehst du, welche Plattformen fertig eingerichtet sind. Das Ergebnis steht in `daten/plattformen/<name>.yaml` und darf von Hand angepasst werden.

## Produkte eintragen

In `produkte.yaml`:

```yaml
produkte:
  - id: slip-001
    name: Spitzenslip schwarz
    preis: 25            # wird exakt so eingestellt
    mindestpreis: 20     # optional: darunter nie
    groesse: M
    farbe: Schwarz
    material: Spitze
    notizen: Nichtraucherhaushalt.
    fotos: [fotos/slip-001]          # Ordner oder einzelne Dateien
    plattformen: [crazyslip, creamsi]
    crazyslip:
      kategorie: ["Slips"]           # Text genau wie im Menü der Seite
      felder: {tragedauer: "1 Tag"}  # Zusatzfelder aus dem Einrichten
    creamsi:
      kategorie: ["Slips & Strings"]
      felder: {tragedauer: "1 Tag"}
```

Weitere Felder: `zustand` (Standard `getragen`), `marke`, `max_rabatt_prozent` (max. 30), `verhandelbar: false` (Festpreis), `versand`.

## Benutzung

```bash
python -m verkaufsagent anmelden crazyslip   # falls die Sitzung abgelaufen ist
python -m verkaufsagent texte                # Beschreibungen ansehen (ohne einzustellen)
python -m verkaufsagent texte slip-001 --neu # Texte neu schreiben lassen
python -m verkaufsagent inserieren           # neue Produkte einstellen
python -m verkaufsagent preise               # Statistik lesen, Preise ggf. senken
python -m verkaufsagent lauf                 # beides (für den Cronjob)
python -m verkaufsagent status               # Übersicht: Status, Preis, Untergrenze, Link
python -m verkaufsagent angebot slip-001 21  # Käuferangebot bewerten
python -m verkaufsagent markieren slip-001 verkauft
```

**Empfohlener Start:** Lass `auto_veroeffentlichen: false` zunächst so. Der Agent füllt dann das Formular sichtbar aus und veröffentlicht erst, wenn du Enter drückst. Wenn die ersten Angebote korrekt sind, stell auf `true`. Ab dann läuft alles vollautomatisch, etwa per Cronjob zweimal täglich:

```
0 9,19 * * * cd /pfad/zu/verkaufsagent && .venv/bin/python -m verkaufsagent lauf >> daten/agent.log 2>&1
```

## Weitere Marktplätze

Für eine weitere Seite legst du eine Datei `daten/plattformen/<name>.yaml` an, zum Beispiel als Kopie von `verkaufsagent/plattformen/definitionen/crazyslip.yaml` mit angepasstem `name`, `anzeigename`, `basis_url` und `stil`. Danach führst du `einrichten <name>` aus.

## Wenn etwas nicht klappt

- **„… ist noch nicht eingerichtet“**: Führe `einrichten <plattform>` aus.
- **„Feld … nicht gefunden“**: Die Seite wurde umgebaut. Führe `einrichten <plattform>` erneut aus. Den Screenshot findest du in `daten/screenshots/`.
- **„Nicht angemeldet“**: Führe `anmelden <plattform>` aus.
- **Status `fehler`** in `status`: Die Fehlermeldung und der Screenshot-Pfad stehen daneben. Beim nächsten Lauf versucht der Agent es erneut.

## Wichtig zu wissen

- **Plattformregeln:** Diese Marktplätze sind nur für Erwachsene und verlangen meist ein verifiziertes Verkäuferkonto. Ob automatisiertes Einstellen erlaubt ist, regeln ihre AGB. Deshalb gibt es Pausen zwischen den Angeboten (Standard: 90 s) und ein Limit pro Lauf, und der Agent versucht nicht, Schutzmaßnahmen der Seiten zu umgehen.
- **Käufernachrichten** beantwortet der Agent nicht selbst. Mit `angebot` bekommst du eine Empfehlung zu jedem Preisvorschlag.

## Tests

```bash
pytest -q
```

Die Tests prüfen die Preisregeln (unter anderem, dass die 30 %-Grenze nie verletzt wird) und die Texte. Außerdem spielen sie den kompletten Ablauf gegen einen nachgebauten Marktplatz durch: Formular per Klick anlernen, Angebot einstellen, keine Doppelangebote, Preis senken, bei vielen Merkern nicht senken, Verkauf erkennen.
