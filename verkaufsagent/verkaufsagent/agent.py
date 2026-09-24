"""Der eigentliche Agent: inseriert neue Produkte und pflegt Preise."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Callable

from .konfiguration import Konfiguration
from .modelle import Inserat, Preisaenderung, Produkt, Texte
from .plattformen import Abgebrochen, Marktplatz, NichtAngemeldet, NichtEingerichtet
from .preise import pruefe_reduzierung
from .speicher import Speicher
from .texte import TextGenerator, pruefe_texte

log = logging.getLogger(__name__)

PlattformFabrik = Callable[[str], Marktplatz]


class Agent:
    def __init__(self, konf: Konfiguration, produkte: list[Produkt], speicher: Speicher,
                 texte: TextGenerator, fabrik: PlattformFabrik, jetzt: Callable[[], datetime] = datetime.now):
        self.konf = konf
        self.produkte = {p.id: p for p in produkte}
        self.speicher = speicher
        self.texte = texte
        self.fabrik = fabrik
        self.jetzt = jetzt
        self._offen: dict[str, Marktplatz] = {}
        self._gesperrt: set[str] = set()

    def _plattform(self, pl: str) -> Marktplatz:
        if pl not in self._offen:
            self._offen[pl] = self.fabrik(pl)
        return self._offen[pl]

    def schliessen(self) -> None:
        for p in self._offen.values():
            p.schliessen()
        self._offen.clear()

    # ---- Texte ------------------------------------------------------------

    def bereite_texte_vor(self, produkt: Produkt, neu: bool = False) -> dict[str, Texte]:
        """Erzeugt Texte (oder nimmt gespeicherte) und legt Entwürfe an."""
        vorhanden = {pl: self.speicher.hole(produkt.id, pl) for pl in produkt.plattformen}
        if not neu and all(i and i.titel and i.beschreibung for i in vorhanden.values()):
            return {pl: Texte(titel=i.titel, beschreibung=i.beschreibung) for pl, i in vorhanden.items()}
        erzeugt = self.texte.erzeuge(produkt)
        for pl in produkt.plattformen:
            inserat = vorhanden[pl] or Inserat(produkt_id=produkt.id, plattform=pl)
            if inserat.status in ("entwurf", "fehler"):
                inserat.titel, inserat.beschreibung = erzeugt[pl].titel, erzeugt[pl].beschreibung
                self.speicher.speichere(inserat)
        return {pl: erzeugt[pl] for pl in produkt.plattformen}

    # ---- Inserieren ---------------------------------------------------------

    def inseriere_neue(self, nur: set[str] | None = None) -> int:
        anzahl = 0
        for produkt in self.produkte.values():
            if nur and produkt.id not in nur:
                continue
            for pl in produkt.plattformen:
                if pl in self._gesperrt:
                    continue
                definition = self.texte.definitionen(pl)
                if not definition.eingerichtet:
                    log.error("%s ist noch nicht eingerichtet (fehlt: %s) – 'python -m verkaufsagent einrichten %s' ausführen",
                              definition.anzeigename, ", ".join(definition.fehlend()), pl)
                    self._gesperrt.add(pl)
                    continue
                inserat = self.speicher.hole(produkt.id, pl)
                if inserat and inserat.status in ("online", "verkauft", "entfernt"):
                    continue
                if anzahl >= self.konf.max_neue_inserate_pro_lauf:
                    log.info("Limit von %d neuen Inseraten pro Lauf erreicht", anzahl)
                    return anzahl
                if anzahl:
                    time.sleep(self.konf.pause_zwischen_inseraten_s)
                if self._inseriere(produkt, pl):
                    anzahl += 1
        return anzahl

    def _inseriere(self, produkt: Produkt, pl: str) -> bool:
        texte = self.bereite_texte_vor(produkt)[pl]
        inserat = self.speicher.hole(produkt.id, pl) or Inserat(produkt_id=produkt.id, plattform=pl)
        probleme = pruefe_texte(texte, self.texte.definitionen(pl))
        if probleme:
            inserat.status, inserat.fehler = "fehler", "Texte ungültig: " + ", ".join(probleme)
            self.speicher.speichere(inserat)
            log.error("%s: %s", inserat.schluessel, inserat.fehler)
            return False

        preis = produkt.preis  # Inseriert wird immer zum vorgegebenen Preis
        plattform = self._plattform(pl)
        try:
            ergebnis = plattform.veroeffentliche(produkt, texte, preis)
        except (NichtAngemeldet, NichtEingerichtet) as e:
            log.error("%s: %s", pl, e)
            self._gesperrt.add(pl)
            return False
        except Abgebrochen:
            log.info("%s: übersprungen", inserat.schluessel)
            return False
        except Exception as e:
            bild = plattform.screenshot(f"{produkt.id}-fehler")
            inserat.status, inserat.fehler = "fehler", f"{e} (Screenshot: {bild})"
            self.speicher.speichere(inserat)
            log.error("%s: Veröffentlichen fehlgeschlagen: %s", inserat.schluessel, inserat.fehler)
            return False

        jetzt = self.jetzt()
        inserat.status, inserat.fehler = "online", None
        inserat.anzeige_id, inserat.url = ergebnis.anzeige_id, ergebnis.url
        inserat.titel, inserat.beschreibung = texte.titel, texte.beschreibung
        preis = ergebnis.preis if ergebnis.preis is not None else preis
        inserat.preis_aktuell, inserat.online_seit = preis, jetzt
        self.speicher.speichere(inserat)
        log.info("%s online: %s (%.2f €)", inserat.schluessel, ergebnis.url, preis)
        return True

    # ---- Pflege -----------------------------------------------------------

    def pflege_inserate(self, statistik: bool = True) -> None:
        for inserat in self.speicher.alle():
            if inserat.status != "online" or inserat.plattform in self._gesperrt:
                continue
            produkt = self.produkte.get(inserat.produkt_id)
            if produkt is None:
                log.warning("%s: Produkt nicht mehr in produkte.yaml – wird nicht angefasst", inserat.schluessel)
                continue
            plattform = self._plattform(inserat.plattform)
            if statistik:
                try:
                    stat = plattform.lese_statistik(inserat)
                    if not stat.aktiv:
                        inserat.status = "entfernt"
                        self.speicher.speichere(inserat)
                        log.info("%s ist nicht mehr aktiv (verkauft/gelöscht)", inserat.schluessel)
                        continue
                    inserat.aufrufe, inserat.favoriten, inserat.nachrichten = stat.aufrufe, stat.favoriten, stat.nachrichten
                    if stat.aufrufe is not None:
                        inserat.statistik_stand = self.jetzt()
                    self.speicher.speichere(inserat)
                except NichtAngemeldet as e:
                    log.error("%s: %s", inserat.plattform, e)
                    self._gesperrt.add(inserat.plattform)
                    continue
                except Exception as e:
                    log.warning("%s: Statistik nicht lesbar: %s", inserat.schluessel, e)

            entscheidung = pruefe_reduzierung(produkt, inserat, self.konf.preise, self.jetzt())
            if entscheidung.neuer_preis is None:
                log.info("%s: Preis bleibt %.2f € (%s)", inserat.schluessel, inserat.preis_aktuell, entscheidung.grund)
                continue
            neu = entscheidung.neuer_preis
            if not produkt.untergrenze() <= neu < inserat.preis_aktuell:  # letzte Sicherung, darf nie greifen
                log.error("%s: Preisregel verletzt (%.2f €) – keine Änderung", inserat.schluessel, neu)
                continue
            try:
                neu = plattform.aendere_preis(inserat, neu, produkt.untergrenze())
            except NichtEingerichtet as e:
                log.warning("%s: Preis sollte auf %.2f € sinken, aber: %s", inserat.schluessel, neu, e)
                continue
            except Exception as e:
                bild = plattform.screenshot(f"{produkt.id}-preis-fehler")
                log.error("%s: Preisänderung fehlgeschlagen: %s (Screenshot: %s)", inserat.schluessel, e, bild)
                continue
            if neu >= inserat.preis_aktuell:
                log.info("%s: keine passende niedrigere Preisstufe – Preis bleibt %.2f €", inserat.schluessel, inserat.preis_aktuell)
                continue
            jetzt = self.jetzt()
            inserat.preisverlauf.append(Preisaenderung(zeitpunkt=jetzt, alt=inserat.preis_aktuell, neu=neu, grund=entscheidung.grund))
            inserat.preis_aktuell, inserat.letzte_preisaenderung = neu, jetzt
            self.speicher.speichere(inserat)
            log.info("%s: Preis %.2f € → %.2f € (%s)", inserat.schluessel, inserat.preisverlauf[-1].alt, neu, entscheidung.grund)

    def lauf(self) -> None:
        self.inseriere_neue()
        self.pflege_inserate()
