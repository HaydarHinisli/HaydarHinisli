# Verkaufsagent – Kleinanzeigen & Vinted

Der Agent inseriert deine Produkte selbstständig auf **Kleinanzeigen** und **Vinted**, schreibt für jedes Inserat einen Titel und eine Beschreibung (Pflicht, immer vorhanden) und pflegt danach die Preise. Dabei hält er sich an deinen Preis und reduziert höchstens um 30 %, und zwar nur, wenn es wirklich angemessen ist.

## So arbeitet der Agent

| Schritt | Was passiert |
|---|---|
| **Beschreiben** | Claude sieht sich deine Fotos und Produktdaten an und schreibt einen Titel und eine Beschreibung pro Plattform: für Kleinanzeigen ausführlich mit Privatverkaufs-Hinweis, für Vinted kompakt mit Hashtags. Bekannte Mängel aus `notizen` werden **immer** genannt, nichts wird erfunden. Ohne API-Schlüssel oder bei einem Fehler nimmt der Agent eine vollständige Textvorlage. **Ohne gültige Beschreibung wird nie inseriert.** |
| **Inserieren** | Ein echter Browser (Playwright) füllt das Formular aus: Fotos, Kategorie, Zustand, Marke, Größe, Preis, Versand, PLZ. Danach schickt er es ab und speichert die Anzeigen-ID. Kein Produkt wird doppelt inseriert. |
| **Preis** | Inseriert wird **immer exakt zu deinem Preis**. |
| **Preispflege** | Der Preis wird nur reduziert, wenn **alle** Bedingungen erfüllt sind: mindestens 14 Tage online, mindestens 7 Tage seit der letzten Senkung, schwache Nachfrage (wenige Aufrufe, keine Favoriten, keine Nachrichten). Bei hohem Interesse wird **nie** gesenkt. Ohne aktuelle Aufrufzahlen wird höchstens um 15 % gesenkt. |
| **Harte Grenze** | Der Preis fällt nie mehr als 30 % unter deinen Preis und nie unter einen gesetzten `mindestpreis`. Diese Grenze ist fest im Code verankert (`MAX_RABATT_ABSOLUT`), nicht nur in der Konfiguration. Mit `verhandelbar: false` wird der Preis nie gesenkt. |
| **Angebote** | `angebot <produkt> <betrag>` sagt dir, ob du ein Käuferangebot annehmen solltest oder welches Gegenangebot passt. Es liegt nie unter der Untergrenze. |
| **Erkennung** | Verkaufte oder gelöschte Inserate werden erkannt und nicht mehr angefasst. |

Beispiel für einen Preis von 45 € mit schwacher Nachfrage: 45 → 42 (Tag 14) → 40 (Tag 21) → 38 → 36 → 35 € (Untergrenze), danach keine weitere Senkung.

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

## Einrichtung

1. **`config.yaml`**: PLZ, Name und Preisregeln eintragen.
2. **`produkte.yaml`**: Produkte eintragen. Fotos kommen z. B. nach `fotos/jacke-001/`. Die wichtigsten Felder:
   - `preis`: dein Preis, zu dem inseriert wird
   - `mindestpreis` (optional): darunter geht der Preis nie
   - `max_rabatt_prozent` (optional, max. 30)
   - `verhandelbar: false`: Festpreis
   - `notizen`: Mängel und Fakten, die in die Beschreibung müssen
   - `vinted.kategorie`: **Pflicht für Vinted**, z. B. `["Herren", "Kleidung", "Jacken & Mäntel"]`
   - `kleinanzeigen.kategorie`: empfohlen, sonst wird der Kategorie-Vorschlag von Kleinanzeigen übernommen
3. **Einmalig anmelden** (öffnet einen Browser, Login inkl. Captcha/2FA machst du selbst; die Sitzung wird gespeichert, dein Passwort nie):
   ```bash
   python -m verkaufsagent anmelden kleinanzeigen
   python -m verkaufsagent anmelden vinted
   ```

## Benutzung

```bash
python -m verkaufsagent texte                # Beschreibungen erzeugen und ansehen (ohne zu inserieren)
python -m verkaufsagent texte jacke-001 --neu   # Texte für ein Produkt neu schreiben lassen
python -m verkaufsagent inserieren           # alle neuen Produkte inserieren
python -m verkaufsagent preise               # Statistik lesen, Preise ggf. senken
python -m verkaufsagent lauf                 # beides (für den Cronjob)
python -m verkaufsagent status               # Übersicht: Status, Preis, Untergrenze, Link
python -m verkaufsagent angebot jacke-001 38 # Käuferangebot bewerten
python -m verkaufsagent markieren jacke-001 verkauft
python -m verkaufsagent uebernehmen <vinted-link>   # vorhandenes Vinted-Inserat übernehmen
```

### Bereits vorhandene Vinted-Inserate übernehmen

Wenn du einen Artikel schon selbst bei Vinted hochgeladen hast, übernimmt ihn der Agent, **ohne ihn neu hochzuladen**:

```bash
python -m verkaufsagent uebernehmen https://www.vinted.de/items/10111548720-unterwasche
```

Der Agent liest Titel, Beschreibung, Preis, Zustand, Marke, Größe und alle Fotos aus deinem Inserat. Die Fotos speichert er in `fotos/vinted-<nummer>/`. Außerdem legt er das Produkt in `produkte.yaml` an und merkt sich das Inserat als „online“. Ab dann pflegt er den Preis nach denselben Regeln. Die Standzeit zählt ab dem Tag, an dem du das Inserat erstellt hast.

Nützliche Optionen:
- `--preis 15`: Grundpreis, von dem aus gerechnet wird (Standard: aktueller Vinted-Preis)
- `--mindestpreis 10`: Untergrenze
- `--auch-kleinanzeigen --ka-kategorie "Mode & Beauty" "Damenbekleidung"`: zusätzlich auf Kleinanzeigen einstellen. Danach `python -m verkaufsagent inserieren vinted-<nummer>` ausführen, der Agent schreibt dafür eine eigene Kleinanzeigen-Beschreibung.
- `--zustand neu_mit_etikett`: falls der Zustand nicht erkannt wird

**Empfohlener Start:** Lass `auto_veroeffentlichen: false` zunächst so. Der Agent füllt dann das Formular sichtbar aus, macht einen Screenshot und veröffentlicht erst, wenn du Enter drückst. Wenn die ersten Inserate korrekt sind, stell auf `true`. Ab dann läuft alles vollautomatisch.

**Vollautomatisch zweimal täglich** (Linux/macOS, `crontab -e`):
```
0 9,19 * * * cd /pfad/zu/verkaufsagent && .venv/bin/python -m verkaufsagent lauf >> daten/agent.log 2>&1
```
Alternativ `python -m verkaufsagent lauf --dauerbetrieb --intervall-h 12`.

## Wenn etwas nicht klappt

- **„Element nicht gefunden: vinted.preis …“**: Die Plattform hat ihre Webseite geändert. Öffne den Screenshot in `daten/screenshots/`, ermittle den neuen Selektor (Rechtsklick → Untersuchen) und trage ihn in `daten/selektoren.yaml` ein. Der Code muss dafür nicht geändert werden, das Format steht in `verkaufsagent/selektoren.yaml`.
- **„Nicht angemeldet“**: Führe `anmelden <plattform>` erneut aus.
- **Status `fehler`** in `status`: Die Fehlermeldung und der Screenshot-Pfad stehen daneben. Beim nächsten Lauf versucht der Agent es erneut.

## Wichtig zu wissen

- **Nutzungsbedingungen:** Weder Kleinanzeigen noch Vinted bieten eine offizielle Schnittstelle zum Inserieren. Automatisierte Nutzung kann gegen deren AGB verstoßen und im schlimmsten Fall zur Sperrung des Kontos führen. Deshalb gibt es Pausen zwischen Inseraten (Standard: 90 s) und ein Limit pro Lauf. Beides solltest du nicht aggressiv herunterdrehen. Der Agent arbeitet mit deinem normalen Konto und versucht nicht, Schutzmaßnahmen der Plattformen zu umgehen.
- **Webseiten ändern sich:** Die Selektoren entsprechen dem aktuellen Aufbau der Seiten. Kleine Änderungen fängst du über `daten/selektoren.yaml` ab.
- **Käufernachrichten** beantwortet der Agent nicht selbst. Mit `angebot` bekommst du aber eine Empfehlung zu jedem Preisvorschlag.

## Tests

```bash
pytest -q
```
Die Tests prüfen die Preisregeln (unter anderem, dass die 30 %-Grenze nie verletzt wird), die Textprüfung und den kompletten Browser-Ablauf für beide Plattformen gegen nachgebaute Formulare: inserieren, keine Doppelinserate, Preis senken, bei hohem Interesse nicht senken, Fehlerbehandlung.
