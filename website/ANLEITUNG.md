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

- **Module** (Intro und Kopfbereich): `de.json`/`en.json` unter `intro.modules` – Name (`app`), Aktion (`action`), Symbol (`icon`), Farbe (`color`). Genau 4 Module mit `"hero": true`, Reihenfolge = Ablauf der Kette. `"trigger": true` zeigt die Uhr am ersten Modul.
- **Intro**: 3D-Fahrt entlang der Kette, ca. 5 s, danach gleiten die Module an ihren Platz im Kopfbereich. Abschalten: `content/site.json` → `"introVariant": "aus"` (Standard `"3d"`).
- **Wann es läuft**: wenn man von außen auf die Startseite kommt – nicht beim Neuladen, nicht über „Zurück“ und nicht, wenn man von einer Unterseite kommt. Es wird bewusst nichts gespeichert (kein Merker), damit keine Einwilligung nötig ist. Ohne Grafikbeschleunigung und bei „Bewegung reduzieren“ entfällt es, die Seite erscheint sofort.
- **Vorschau** (läuft bei jedem Aufruf): `/?intro=3d`
- **Programmcode**: `src/intro3d.js`. Nur wer diesen Code ändert, muss einmalig `npm install` und danach `npm run build:intro3d` ausführen. Texte, Farben und Symbole brauchen diesen Schritt nicht.
- **Symbole**: `bag`, `sheet`, `spark` und `mail` sind flächige, plastische Symbole (Kopfbereich und Intro); alle übrigen Namen sind Liniensymbole und erscheinen im Intro ohne Symbol.

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
4. Wenn alles passt, `"published": true` setzen. Erst dann wird die Seite gebaut und erscheint in der Navigation („Anwendungsfälle“), auf der Übersichtsseite und in der Sitemap. Entwürfe kommen nicht ins Upload-Paket; zur Vorschau `PREVIEW_DRAFTS=1 npm start`.
5. Nur echte, laufende Projekte als Fallstudie veröffentlichen, keine erfundenen Zahlen. Geplantes klar als Lösungsbeispiel kennzeichnen.

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

## 5. Hell und dunkel

- Oben in der Kopfzeile können Besucher zwischen heller und dunkler Ansicht umschalten. Die Wahl wird nur im Browser des Besuchers gespeichert (localStorage `4e-theme`), keine Cookies, keine personenbezogenen Daten.
- Ohne eigene Wahl richtet sich die Seite nach der Hell/Dunkel-Einstellung des Geräts (`content/site.json` → `"themeAuto": true`). Mit `false` gilt immer der Standard aus `"theme"` (`"futur"` = dunkel, `"hell"` = hell).
