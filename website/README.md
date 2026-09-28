# 4elements-digital.de

Statische, zweisprachige Website (DE unter `/`, EN unter `/en/`) für 4ELEMENTS e.K. Keine Abhängigkeiten, keine Datenbank, keine externen Dienste.

- `content/`: alle Texte (`de.json`, `en.json`), Firmendaten (`site.json`), Anwendungsfälle, Datenschutztext
- `assets/`: CSS, JS, lokale Schriften (Geist 400/500/600, Geist Mono 400, Instrument Serif kursiv; alle SIL OFL), Bilder
- `static/`: Dateien für das Web-Wurzelverzeichnis (`.htaccess`, Favicons)
- `src/intro3d.js`: 3D-Intro (Three.js); gebündelt nach `assets/js/intro3d.js` mit `npm run build:intro3d` (einmalig `npm install`)
- `build.mjs`: erzeugt `dist/` (HTML-Seiten, `sitemap.xml` mit hreflang, `robots.txt`, 404-Seite)
- `dist/`: fertige Website zum Hochladen (wird von `npm run build` neu erzeugt, nicht von Hand ändern)

Pflege und Veröffentlichung: siehe [ANLEITUNG.md](ANLEITUNG.md).

## Offene Punkte

- Ansprache: umgesetzt mit „du“ (Stand Briefing)
- Englische Texte: Entwurfsübersetzung als Platzhalter in `content/en.json`
- Umsatzsteuer-ID, Telefon, Porträtfoto: Felder in `content/site.json` (leer = ausgeblendet bzw. Platzhalter)
- Datenschutzerklärung: Platzhalter in `content/rechtliches/`
- Beispiel-Anwendungsfall: Platzhaltertexte, `"published": false`
