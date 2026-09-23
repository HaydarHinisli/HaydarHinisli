"""Kommandozeile: python -m verkaufsagent <befehl>"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from .agent import Agent
from .konfiguration import lade_konfiguration, lade_produkte
from .modelle import Plattform, Zustand
from .preise import bewerte_angebot
from .speicher import Speicher
from .texte import TextGenerator, pruefe_texte


def _agent(args, sichtbar: bool = False):
    from playwright.sync_api import sync_playwright

    from .plattformen import KLASSEN

    konf = lade_konfiguration(Path(args.config))
    produkte = lade_produkte(Path(args.produkte))
    pw = sync_playwright().start()
    # Ohne Auto-Veröffentlichen wird das Formular zur Kontrolle sichtbar angezeigt
    zeigen = sichtbar or not konf.auto_veroeffentlichen
    agent = Agent(konf, produkte, Speicher(konf.datenordner), TextGenerator(konf.ki),
                  fabrik=lambda pl: KLASSEN[pl](pw, konf, sichtbar=zeigen))
    return agent, pw


def cmd_anmelden(args) -> None:
    from playwright.sync_api import sync_playwright

    from .plattformen import KLASSEN

    konf = lade_konfiguration(Path(args.config))
    with sync_playwright() as pw:
        p = KLASSEN[Plattform(args.plattform)](pw, konf, sichtbar=True)
        try:
            p.anmelden_interaktiv()
            print(f"✔ Angemeldet bei {args.plattform}. Die Sitzung wird gespeichert.")
        finally:
            p.schliessen()


def cmd_texte(args) -> None:
    konf = lade_konfiguration(Path(args.config))
    produkte = lade_produkte(Path(args.produkte))
    speicher = Speicher(konf.datenordner)
    agent = Agent(konf, produkte, speicher, TextGenerator(konf.ki), fabrik=lambda pl: None)  # type: ignore[arg-type,return-value]
    for p in produkte:
        if args.produkt and p.id not in args.produkt:
            continue
        for pl, t in agent.bereite_texte_vor(p, neu=args.neu).items():
            probleme = pruefe_texte(t, pl, p)
            print(f"\n=== {p.id} @ {pl.value} ({p.preis:.2f} €) {'⚠ ' + ', '.join(probleme) if probleme else '✔'}")
            print(f"Titel: {t.titel}\n\n{t.beschreibung}")


def cmd_inserieren(args) -> None:
    agent, pw = _agent(args)
    try:
        n = agent.inseriere_neue(set(args.produkt) if args.produkt else None)
        print(f"{n} neue(s) Inserat(e) veröffentlicht.")
    finally:
        agent.schliessen()
        pw.stop()


def cmd_preise(args) -> None:
    agent, pw = _agent(args)
    try:
        agent.pflege_inserate()
    finally:
        agent.schliessen()
        pw.stop()


def cmd_lauf(args) -> None:
    while True:
        agent, pw = _agent(args)
        try:
            agent.lauf()
        finally:
            agent.schliessen()
            pw.stop()
        if not args.dauerbetrieb:
            return
        logging.info("Nächster Lauf in %d Stunden", args.intervall_h)
        time.sleep(args.intervall_h * 3600)


def cmd_status(args) -> None:
    konf = lade_konfiguration(Path(args.config))
    produkte = {p.id: p for p in lade_produkte(Path(args.produkte))}
    inserate = Speicher(konf.datenordner).alle()
    if not inserate:
        print("Noch keine Inserate.")
    for i in inserate:
        p = produkte.get(i.produkt_id)
        grenze = f"{p.untergrenze():.2f}" if p else "?"
        preis = f"{i.preis_aktuell:.2f}" if i.preis_aktuell is not None else "-"
        tage = f"{(datetime.now() - i.online_seit).days} T" if i.online_seit else ""
        print(f"{i.schluessel:<35} {i.status:<9} {preis:>8} € (min {grenze}) {tage:>5}  {i.url or i.fehler or ''}")


def cmd_angebot(args) -> None:
    konf = lade_konfiguration(Path(args.config))
    produkte = {p.id: p for p in lade_produkte(Path(args.produkte))}
    p = produkte[args.produkt_id]
    inserat = Speicher(konf.datenordner).hole(p.id, Plattform(args.plattform))
    preis = inserat.preis_aktuell if inserat and inserat.preis_aktuell else p.preis
    tage = (datetime.now() - inserat.online_seit).days if inserat and inserat.online_seit else 0
    b = bewerte_angebot(p, preis, args.betrag, tage)
    print(f"Angebot {args.betrag:.2f} € für {p.name} (aktuell {preis:.2f} €): "
          f"{b.aktion.upper()}{f' → {b.betrag:.2f} €' if b.betrag else ''} – {b.begruendung}")


def cmd_markieren(args) -> None:
    konf = lade_konfiguration(Path(args.config))
    speicher = Speicher(konf.datenordner)
    for pl in Plattform:
        i = speicher.hole(args.produkt_id, pl)
        if i:
            i.status = args.status
            speicher.speichere(i)
            print(f"{i.schluessel} → {args.status}")


def cmd_uebernehmen(args) -> None:
    from playwright.sync_api import sync_playwright

    from .plattformen.vinted import Vinted, artikel_id_aus_url
    from .uebernahme import baue_produkt, registriere_inserat, trage_ein

    konf = lade_konfiguration(Path(args.config))
    produkte_datei = Path(args.produkte)
    speicher = Speicher(konf.datenordner)
    anzeige_id = artikel_id_aus_url(args.url)
    for i in speicher.alle():
        if i.plattform == Plattform.vinted and i.anzeige_id == anzeige_id:
            raise SystemExit(f"Vinted-Artikel {anzeige_id} ist bereits als '{i.produkt_id}' übernommen.")
    produkt_id = args.id or f"vinted-{anzeige_id}"
    foto_ordner = produkte_datei.resolve().parent / "fotos" / produkt_id

    with sync_playwright() as pw:
        vinted = Vinted(pw, konf)
        try:
            artikel = vinted.lese_artikel(args.url)
            print(f"Gefunden: „{artikel.titel}“ – {artikel.preis} € – Zustand: {artikel.zustand or '?'} – "
                  f"{len(artikel.foto_urls)} Foto(s)")
            fotos = vinted.lade_fotos(artikel.foto_urls, foto_ordner)
        finally:
            vinted.schliessen()

    eintrag = baue_produkt(
        artikel, produkt_id, fotos, produkte_datei.resolve().parent,
        preis=args.preis, mindestpreis=args.mindestpreis,
        zustand=Zustand(args.zustand) if args.zustand else None,
        kleinanzeigen=args.auch_kleinanzeigen, ka_kategorie=args.ka_kategorie or [],
    )
    produkt = trage_ein(produkte_datei, eintrag)
    inserat = registriere_inserat(speicher, produkt, artikel, datetime.now())
    print(f"✔ Übernommen als '{produkt.id}' ({len(fotos)} Foto(s) in {foto_ordner}).")
    print(f"  Preis {inserat.preis_aktuell:.2f} €, Untergrenze {produkt.untergrenze():.2f} €, "
          f"online seit {inserat.online_seit:%d.%m.%Y}. Der Agent pflegt ab jetzt den Preis.")
    if args.auch_kleinanzeigen:
        print(f"  Für Kleinanzeigen: 'python -m verkaufsagent inserieren {produkt.id}' ausführen.")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="verkaufsagent", description="Inseriert Produkte auf Kleinanzeigen und Vinted.")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--produkte", default="produkte.yaml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="befehl", required=True)

    s = sub.add_parser("anmelden", help="Einmalig im Browser anmelden (Sitzung wird gespeichert)")
    s.add_argument("plattform", choices=[p.value for p in Plattform])
    s.set_defaults(f=cmd_anmelden)

    s = sub.add_parser("texte", help="Titel/Beschreibungen erzeugen und anzeigen (ohne zu inserieren)")
    s.add_argument("produkt", nargs="*")
    s.add_argument("--neu", action="store_true", help="Texte neu erzeugen")
    s.set_defaults(f=cmd_texte)

    s = sub.add_parser("inserieren", help="Neue Produkte inserieren")
    s.add_argument("produkt", nargs="*")
    s.set_defaults(f=cmd_inserieren)

    s = sub.add_parser("preise", help="Statistik lesen und Preise ggf. reduzieren")
    s.set_defaults(f=cmd_preise)

    s = sub.add_parser("lauf", help="Inserieren + Preispflege (für Cronjob)")
    s.add_argument("--dauerbetrieb", action="store_true")
    s.add_argument("--intervall-h", type=float, default=12)
    s.set_defaults(f=cmd_lauf)

    s = sub.add_parser("uebernehmen", help="Bestehendes Vinted-Inserat übernehmen (wird nicht neu hochgeladen)")
    s.add_argument("url", help="Link oder ID des Vinted-Artikels")
    s.add_argument("--id", help="Eigene Produkt-ID (Standard: vinted-<artikelnummer>)")
    s.add_argument("--preis", type=float, help="Dein Grundpreis (Standard: aktueller Vinted-Preis)")
    s.add_argument("--mindestpreis", type=float)
    s.add_argument("--zustand", choices=[z.value for z in Zustand])
    s.add_argument("--auch-kleinanzeigen", action="store_true", help="Zusätzlich auf Kleinanzeigen inserieren")
    s.add_argument("--ka-kategorie", nargs="+", metavar="EBENE", help='z. B. --ka-kategorie "Mode & Beauty" "Damenbekleidung"')
    s.set_defaults(f=cmd_uebernehmen)

    s = sub.add_parser("status", help="Übersicht aller Inserate")
    s.set_defaults(f=cmd_status)

    s = sub.add_parser("angebot", help="Käuferangebot bewerten")
    s.add_argument("produkt_id")
    s.add_argument("betrag", type=float)
    s.add_argument("--plattform", default="kleinanzeigen", choices=[p.value for p in Plattform])
    s.set_defaults(f=cmd_angebot)

    s = sub.add_parser("markieren", help="Produkt manuell als verkauft/entfernt markieren")
    s.add_argument("produkt_id")
    s.add_argument("status", choices=["verkauft", "entfernt", "entwurf"])
    s.set_defaults(f=cmd_markieren)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    from .plattformen.basis import PlattformFehler

    try:
        args.f(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except (PlattformFehler, ValueError, FileNotFoundError) as e:
        sys.exit(f"Fehler: {e}")
