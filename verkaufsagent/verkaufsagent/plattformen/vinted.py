"""Vinted.de – Inserieren, Preis ändern, Statistik lesen."""
from __future__ import annotations

import html as html_lib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ..modelle import Inserat, Plattform, Produkt, Texte
from .basis import NichtAngemeldet, PlattformBasis, PlattformFehler, Statistik, Veroeffentlicht, preis_text

log = logging.getLogger(__name__)

BASIS = "https://www.vinted.de"
PAKET = {"S": "Klein", "M": "Mittel", "L": "Groß"}


@dataclass
class VintedArtikel:
    """Daten eines bereits bestehenden Vinted-Inserats."""
    anzeige_id: str
    url: str
    titel: str
    beschreibung: str
    preis: float | None
    zustand: str | None = None
    marke: str | None = None
    groesse: str | None = None
    farbe: str | None = None
    foto_urls: list[str] = field(default_factory=list)
    erstellt: datetime | None = None
    aufrufe: int | None = None
    favoriten: int | None = None
    aktiv: bool = True


def artikel_id_aus_url(url_oder_id: str) -> str:
    treffer = re.search(r"/items/(\d+)", url_oder_id) or re.fullmatch(r"\s*(\d+)\s*", url_oder_id)
    if not treffer:
        raise ValueError(f"Keine Vinted-Artikel-ID in '{url_oder_id}' gefunden")
    return treffer.group(1)


def _preis(wert) -> float | None:
    if isinstance(wert, dict):
        wert = wert.get("amount")
    if wert in (None, ""):
        return None
    try:
        return round(float(str(wert).replace(",", ".")), 2)
    except ValueError:
        return None


def _zeit(wert) -> datetime | None:
    if isinstance(wert, (int, float)):
        return datetime.fromtimestamp(wert, tz=timezone.utc).astimezone().replace(tzinfo=None)
    if isinstance(wert, str) and wert:
        try:
            return datetime.fromisoformat(wert.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
        except ValueError:
            return None
    return None


class Vinted(PlattformBasis):
    plattform = Plattform.vinted
    startseite = BASIS

    def ist_angemeldet(self) -> bool:
        self.page.goto(f"{BASIS}/items/new")
        self.page.wait_for_load_state("domcontentloaded")
        if "signup" in self.page.url or "login" in self.page.url:
            return False
        return self.optional("fotos", 8000, sichtbar=False) is not None

    def _auswahl(self, feld: str, pfad: list[str], pflicht: bool) -> None:
        """Öffnet ein Vinted-Dropdown und klickt sich durch die Einträge."""
        if not pfad:
            return
        eingabe = self.finde(feld) if pflicht else self.optional(feld)
        if eingabe is None:
            return
        eingabe.click()
        try:
            for ebene in pfad:
                inhalt = self.finde("dropdown_inhalt", 5000)
                inhalt.get_by_text(ebene, exact=True).first.click(timeout=5000)
                self.page.wait_for_timeout(400)
        except Exception as e:
            if pflicht:
                raise PlattformFehler(f"Vinted-{feld} '{' > '.join(pfad)}' nicht auswählbar: {e}") from e
            log.warning("Vinted-%s '%s' nicht gesetzt: %s", feld, " > ".join(pfad), e)
            self.page.keyboard.press("Escape")

    def _marke(self, marke: str | None) -> None:
        """Marke ist optional – Probleme hier brechen das Inserat nie ab."""
        if not marke:
            return
        feld = self.optional("marke")
        if not feld:
            return
        try:
            feld.click()
            suche = self.optional("marke_suche", 3000)
            if suche is not None:
                suche.fill(marke)
            elif feld.is_editable():
                feld.fill(marke)
            self.page.wait_for_timeout(1200)
            inhalt = self.finde("dropdown_inhalt", 3000)
            treffer = inhalt.get_by_text(marke, exact=True).first
            if not treffer.count():
                # z. B. "<Marke> als Marke verwenden"
                treffer = inhalt.get_by_text(re.compile(re.escape(marke), re.I)).first
            treffer.click(timeout=3000)
        except Exception as e:
            log.warning("Marke '%s' auf Vinted nicht gesetzt: %s", marke, e)
            self.page.keyboard.press("Escape")

    def veroeffentliche(self, produkt: Produkt, texte: Texte, preis: float) -> Veroeffentlicht:
        if not produkt.fotos:
            raise PlattformFehler("Vinted verlangt mindestens ein Foto")
        if not produkt.vinted.kategorie:
            raise PlattformFehler("Für Vinted muss 'vinted.kategorie' im Produkt angegeben sein")
        self.page.goto(f"{BASIS}/items/new")
        if "signup" in self.page.url or "login" in self.page.url:
            raise NichtAngemeldet("Nicht bei Vinted angemeldet – 'verkaufsagent anmelden vinted' ausführen")
        self.cookies_akzeptieren()

        self.finde("fotos", sichtbar=False).set_input_files([str(f) for f in produkt.fotos[:20]])
        self.page.wait_for_timeout(2000 + 1500 * min(len(produkt.fotos), 20))

        self.finde("titel").fill(texte.titel)
        self.finde("beschreibung").fill(texte.beschreibung)
        self._auswahl("kategorie", produkt.vinted.kategorie, pflicht=True)
        self._marke(produkt.marke)
        if produkt.groesse:
            self._auswahl("groesse", [produkt.groesse], pflicht=False)
        self._auswahl("zustand", [produkt.zustand.text], pflicht=True)
        if produkt.farbe:
            self._auswahl("farbe", [produkt.farbe.split("/")[0].strip().capitalize()], pflicht=False)

        self.finde("preis").fill(preis_text(preis))
        paket = self.page.get_by_text(PAKET[produkt.vinted.paketgroesse], exact=True).first
        if paket.count():
            paket.click()

        self.bestaetigen_oder_abbrechen(produkt)
        self.finde("absenden").click()
        self.page.wait_for_url(re.compile(r"/items/\d+"), timeout=90000)
        anzeige_id = re.search(r"/items/(\d+)", self.page.url).group(1)
        return Veroeffentlicht(anzeige_id, f"{BASIS}/items/{anzeige_id}")

    def aendere_preis(self, inserat: Inserat, preis: float) -> None:
        self.page.goto(f"{BASIS}/items/{inserat.anzeige_id}/edit")
        if "signup" in self.page.url or "login" in self.page.url:
            raise NichtAngemeldet("Nicht bei Vinted angemeldet")
        self.cookies_akzeptieren()
        self.finde("preis").fill(preis_text(preis))
        self.finde("absenden").click()
        self.page.wait_for_url(lambda url: "/edit" not in url, timeout=60000)

    def lese_artikel(self, url_oder_id: str) -> VintedArtikel:
        """Liest ein bestehendes Inserat – zuerst über die Vinted-API, sonst aus der Artikelseite."""
        anzeige_id = artikel_id_aus_url(url_oder_id)
        url = f"{BASIS}/items/{anzeige_id}"
        _, daten = self.hole_json(f"{BASIS}/api/v2/items/{anzeige_id}")
        item = (daten or {}).get("item")
        if item:
            fotos = [f.get("full_size_url") or f.get("url") for f in item.get("photos") or []]
            return VintedArtikel(
                anzeige_id=anzeige_id, url=url,
                titel=(item.get("title") or "").strip(),
                beschreibung=(item.get("description") or "").strip(),
                preis=_preis(item.get("price")) or _preis(item.get("price_numeric")),
                zustand=item.get("status") or None,
                marke=item.get("brand_title") or (item.get("brand_dto") or {}).get("title") or None,
                groesse=item.get("size_title") or None,
                farbe=item.get("color1") or None,
                foto_urls=[f for f in fotos if f],
                erstellt=_zeit(item.get("created_at_ts") or item.get("created_at")),
                aufrufe=item.get("view_count"), favoriten=item.get("favourite_count"),
                aktiv=not (item.get("is_closed") or item.get("is_sold") or item.get("is_hidden")),
            )
        # Rückfall: Öffentliche Artikelseite (Open-Graph-Metadaten)
        antwort = self.page.goto(url)
        if antwort is not None and antwort.status in (404, 410):
            raise PlattformFehler(f"Vinted-Artikel {anzeige_id} existiert nicht (mehr)")
        quelltext = self.page.content()

        def meta(name: str) -> str | None:
            m = re.search(rf'<meta[^>]+(?:property|name)="{re.escape(name)}"[^>]+content="([^"]*)"', quelltext)
            return html_lib.unescape(m.group(1)).strip() if m else None

        titel = meta("og:title") or ""
        if not titel:
            raise PlattformFehler(f"Vinted-Artikel {anzeige_id} konnte nicht gelesen werden")
        fotos = re.findall(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', quelltext)
        return VintedArtikel(
            anzeige_id=anzeige_id, url=url, titel=titel,
            beschreibung=meta("og:description") or "",
            preis=_preis(meta("product:price:amount")),
            marke=meta("product:brand"),
            foto_urls=[html_lib.unescape(f) for f in fotos],
        )

    def lade_fotos(self, urls: list[str], ordner: Path) -> list[Path]:
        ordner.mkdir(parents=True, exist_ok=True)
        pfade = []
        for nr, foto_url in enumerate(urls, 1):
            antwort = self.page.goto(foto_url)
            if antwort is None or not antwort.ok:
                log.warning("Foto %d nicht ladbar: %s", nr, foto_url)
                continue
            typ = (antwort.headers.get("content-type") or "").lower()
            endung = ".png" if "png" in typ else ".webp" if "webp" in typ else ".jpg"
            pfad = ordner / f"{nr:02d}{endung}"
            pfad.write_bytes(antwort.body())
            pfade.append(pfad)
        return pfade

    def lese_statistik(self, inserat: Inserat) -> Statistik:
        stat = Statistik()
        status, daten = self.hole_json(f"{BASIS}/api/v2/items/{inserat.anzeige_id}")
        if status in (404, 410):
            # Nur als gelöscht werten, wenn auch die öffentliche Artikelseite fehlt
            # (ein 404 der API allein kann auch eine geänderte Schnittstelle sein).
            seite = self.page.goto(f"{BASIS}/items/{inserat.anzeige_id}")
            if seite is not None and seite.status in (404, 410):
                stat.aktiv = False
            return stat
        if daten:
            item = daten.get("item", {})
            stat.aufrufe = item.get("view_count")
            stat.favoriten = item.get("favourite_count")
            if item.get("is_closed") or item.get("is_sold") or item.get("is_hidden"):
                stat.aktiv = False
        else:
            log.debug("Vinted-Statistik nicht lesbar (HTTP %s)", status)
        return stat
