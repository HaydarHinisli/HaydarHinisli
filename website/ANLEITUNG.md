# Anleitung: Texte ändern und Anwendungsfall-Seiten anlegen

Voraussetzung: [Node.js](https://nodejs.org) (Version 18 oder neuer) ist installiert. Weitere Programme sind nicht nötig.

## 1. Texte ändern

| Was | Datei |
|---|---|
| Alle deutschen Texte (Startseite, Navigation, Fußzeile, Impressum-Beschriftungen) | `content/de.json` |
| Alle englischen Texte (gleicher Aufbau) | `content/en.json` |
| Firmendaten, Umsatzsteuer-ID, Telefon, Porträtfoto | `content/site.json` |
| Datenschutzerklärung | `content/rechtliches/datenschutz.de.html` und `.en.html` |

Nur den Text **zwischen den Anführungszeichen** ändern. Anführungszeichen im Text als `\"` schreiben. Die Zeichen `{ } [ ] , :` nicht löschen.

### Intro und Workflow-Grafik

- **Module** (Intro und Kopfbereich): `de.json`/`en.json` unter `intro.modules` – Name (`app`), Aktion (`action`), Symbol (`icon`), Farbe (`color`). Genau 9 Module, Reihenfolge = Rolle im Ablauf. Die 4 Module mit `"hero": true` bilden danach die Kette im Kopfbereich.
- **Variante**: `content/site.json` → `"introVariant"`: `"clean"`, `"verspielt"` oder `"aus"`.
- **Vorschau** (läuft bei jedem Aufruf): `/?intro=clean` bzw. `/?intro=verspielt`. Sonst läuft das Intro nur beim ersten Besuch pro Sitzung.

## 2. Anwendungsfall-Seite anlegen

1. Die Datei `content/anwendungsfaelle/shopify-bestellungen-google-sheets.json` kopieren und umbenennen, z. B. `amazon-bestandswarnung.json`.
2. In der Kopie für **beide Sprachen** (`"de"` und `"en"`) ausfüllen:
   - `slug`: die Adresse, nur Kleinbuchstaben, Ziffern und Bindestriche, **keine Umlaute** (z. B. `amazon-bestandswarnung` → `4elements-digital.de/amazon-bestandswarnung/`)
   - `metaTitle`, `metaDescription`: Titel und Beschreibung für Google
   - `h1`: die Überschrift in Suchsprache
   - `teaser`: ein Satz für die Übersichtsseite
   - `problem`, `solution`: Absätze, jeder Absatz in eigenen Anführungszeichen
   - `flowSteps`: die Schritte der Ablauf-Grafik (3–5 kurze Begriffe)
   - `result`: die Ergebnis-Punkte
   - `screenshot`: Dateiname des Make-Screenshots (siehe 3.), `screenshotAlt`: Bildbeschreibung
3. `order` bestimmt die Reihenfolge in der Übersicht.
4. Wenn alles passt, `"published": true` setzen. Erst dann erscheint die Seite in der Navigation („Anwendungsfälle“), auf der Übersichtsseite und in der Sitemap. Vorher ist sie nur über die direkte Adresse erreichbar und für Google gesperrt.

## 3. Bilder

Bilder immer als **WebP** in `assets/img/` ablegen (umwandeln z. B. mit squoosh.app, Qualität ca. 80, Breite max. 1600 px). Dann nur den Dateinamen in die JSON-Datei eintragen, z. B. `"screenshot": "shopify-sheets.webp"`. Porträtfoto: Hochformat, am besten 4:5, Eintrag `"portrait"` in `content/site.json`.

## 4. Bauen, prüfen, hochladen

```bash
npm run build     # erzeugt die fertige Website im Ordner dist/
npm start         # baut und zeigt eine Vorschau unter http://localhost:8080
```

Bei einem Tippfehler in einer JSON-Datei nennt `npm run build` die Datei und die Stelle.

**Hochladen:** Den **Inhalt** des Ordners `dist/` (inklusive der versteckten Datei `.htaccess`) per SFTP in das Web-Verzeichnis der Domain bei IONOS kopieren (z. B. mit FileZilla; Zugangsdaten im IONOS-Kundenbereich unter „Hosting → SFTP & SSH“). Bestehende Dateien überschreiben.

## Wichtig

- Keine Schriften, Skripte, Videos oder Bilder von fremden Servern einbinden, sonst werden Cookie-Banner und eine angepasste Datenschutzerklärung nötig. Die `.htaccess` blockiert solche Einbindungen zusätzlich.
