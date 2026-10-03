# 4elements-digital.de

Statische, zweisprachige Website (DE unter `/`, EN unter `/en/`) für 4ELEMENTS e.K. Keine Abhängigkeiten, keine Datenbank, keine externen Dienste.

- `content/`: alle Texte (`de.json`, `en.json`), Firmendaten (`site.json`), Anwendungsfälle, Datenschutztext
- `assets/`: CSS, JS, lokale Schriften (Geist 400/500/600, Geist Mono 400, Instrument Serif kursiv; alle SIL OFL), Bilder
- `static/`: Dateien für das Web-Wurzelverzeichnis (`.htaccess`, Favicons)
- `src/intro3d.js`: 3D-Intro (Three.js); gebündelt nach `assets/js/intro3d.js` mit `npm run build:intro3d` (einmalig `npm install`)
- `build.mjs`: erzeugt `dist/` (HTML-Seiten, `sitemap.xml` mit hreflang, `robots.txt`, 404-Seite)
- `dist/`: fertige Website zum Hochladen (wird von `npm run build` neu erzeugt, nicht von Hand ändern)

Pflege und Veröffentlichung: siehe [ANLEITUNG.md](ANLEITUNG.md).

## Stand

Fertig gebaut, getestet (alle Seiten DE/EN, hell und dunkel, Desktop und Smartphone, mit den Sicherheitsregeln der `.htaccess`), Lighthouse 96–100.

## Vor dem Livegang noch nötig (Inhalte vom Inhaber)

- Datenschutzerklärung: verfasst (`content/rechtliches/`), vor dem Livegang einmal prüfen lassen bzw. mit den eigenen Angaben abgleichen (z. B. IONOS-Auftragsverarbeitungsvertrag abschließen)
- Umsatzsteuer-ID in `content/site.json` (leer = Abschnitt im Impressum ausgeblendet)
- Englische Texte in `content/en.json` gegenlesen (Entwurfsübersetzung)
- Optional: Porträtfoto, Telefonnummer (`content/site.json`), Anwendungsfall-Seite befüllen und `"published": true`
