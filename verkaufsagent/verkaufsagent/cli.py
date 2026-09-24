"""Kommandozeile: python -m verkaufsagent <befehl>"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

from .agent import Agent
from .konfiguration import Konfiguration, lade_konfiguration, lade_produkte
from .plattformdef import Register
from .preise import bewerte_angebot
from .speicher import Speicher
from .texte import TextGenerator, pruefe_texte


def _grundlagen(args) -> tuple[Konfiguration, Register]:
    konf = lade_konfiguration(Path(args.config))
    return konf, Register(konf.datenordner)


def _marktplatz(pw, konf: Konfiguration, register: Register, name: str, sichtbar: bool = False):
    from .plattformen import Marktplatz

    return Marktplatz(pw, konf, register.lade(name), sichtbar=sichtbar)


def _agent(args):
    from playwright.sync_api import sync_playwright

    konf, register = _grundlagen(args)
    produkte = lade_produkte(Path(args.produkte))
    for p in produkte:  # unbekannte Plattformen früh melden
        for pl in p.plattformen:
            register.lade(pl)
    pw = sync_playwright().start()
    # Ohne Auto-Veröffentlichen wird das Formular zur Kontrolle sichtbar angezeigt
    sichtbar = not konf.auto_veroeffentlichen
    agent = Agent(konf, produkte, Speicher(konf.datenordner), TextGenerator(konf.ki, register.lade),
                  fabrik=lambda pl: _marktplatz(pw, konf, register, pl, sichtbar))
    return agent, pw


def cmd_plattformen(args) -> None:
    _, register = _grundlagen(args)
    for name in register.namen():
        d = register.lade(name)
        zustand = "✔ eingerichtet" if d.eingerichtet else f"⚠ nicht eingerichtet (fehlt: {', '.join(d.fehlend())})"
        extras = [t for t, ok in (("Preisänderung", d.bearbeiten_url), ("Statistik", d.aufrufe or d.favoriten)) if ok]
        print(f"{name:<14} {d.anzeigename:<14} {zustand}{'  + ' + ', '.join(extras) if extras else ''}")


def cmd_anmelden(args) -> None:
    from playwright.sync_api import sync_playwright

    konf, register = _grundlagen(args)
    with sync_playwright() as pw:
        m = _marktplatz(pw, konf, register, args.plattform, sichtbar=True)
        try:
            m.anmelden_interaktiv()
            print(f"✔ Angemeldet bei {m.d.anzeigename}. Die Sitzung wird gespeichert.")
        finally:
            m.schliessen()


def cmd_einrichten(args) -> None:
    from playwright.sync_api import sync_playwright

    from .anlernen import Assistent

    konf, register = _grundlagen(args)
    with sync_playwright() as pw:
        m = _marktplatz(pw, konf, register, args.plattform, sichtbar=True)
        try:
            Assistent(m, register).ausfuehren()
        finally:
            m.schliessen()


def cmd_login(args) -> None:
    from playwright.sync_api import sync_playwright

    from .anlernen import Assistent

    konf, register = _grundlagen(args)
    with sync_playwright() as pw:
        m = _marktplatz(pw, konf, register, args.plattform, sichtbar=True)
        try:
            Assistent(m, register).login_anlernen()
        finally:
            m.schliessen()


def cmd_zugang(args) -> None:
    """Nur Benutzername/Passwort neu speichern (ohne die Anmeldung neu anzulernen)."""
    import getpass

    from .zugang import speichere_zugang

    konf, register = _grundlagen(args)
    d = register.lade(args.plattform)
    print(f"Zugangsdaten für {d.anzeigename} neu speichern.")
    benutzer = input("Benutzername bzw. E-Mail: ").strip()
    while True:
        passwort = getpass.getpass("Passwort (wird beim Tippen nicht angezeigt): ")
        if passwort and passwort == getpass.getpass("Passwort noch einmal zur Kontrolle: "):
            break
        print("Die beiden Eingaben stimmen nicht überein (oder sind leer) – bitte noch einmal.")
    speichere_zugang(konf.datenordner, d.name, benutzer, passwort)
    print(f"✔ Gespeichert ({len(passwort)} Zeichen).")


def cmd_texte(args) -> None:
    konf, register = _grundlagen(args)
    produkte = lade_produkte(Path(args.produkte))
    agent = Agent(konf, produkte, Speicher(konf.datenordner), TextGenerator(konf.ki, register.lade),
                  fabrik=lambda pl: None)  # type: ignore[arg-type,return-value]
    for p in produkte:
        if args.produkt and p.id not in args.produkt:
            continue
        for pl, t in agent.bereite_texte_vor(p, neu=args.neu).items():
            probleme = pruefe_texte(t, register.lade(pl))
            print(f"\n=== {p.id} @ {pl} ({p.preis:.2f} €) {'⚠ ' + ', '.join(probleme) if probleme else '✔'}")
            print(f"Titel: {t.titel}\n\n{t.beschreibung}")


def cmd_inserieren(args) -> None:
    agent, pw = _agent(args)
    try:
        n = agent.inseriere_neue(set(args.produkt) if args.produkt else None)
        print(f"{n} neue(s) Angebot(e) veröffentlicht.")
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
        logging.info("Nächster Lauf in %s Stunden", args.intervall_h)
        time.sleep(args.intervall_h * 3600)


def cmd_status(args) -> None:
    konf = lade_konfiguration(Path(args.config))
    produkte = {p.id: p for p in lade_produkte(Path(args.produkte))}
    inserate = Speicher(konf.datenordner).alle()
    if not inserate:
        print("Noch keine Angebote.")
    for i in inserate:
        p = produkte.get(i.produkt_id)
        grenze = f"{p.untergrenze():.2f}" if p else "?"
        preis = f"{i.preis_aktuell:.2f}" if i.preis_aktuell is not None else "-"
        tage = f"{(datetime.now() - i.online_seit).days} T" if i.online_seit else ""
        print(f"{i.schluessel:<35} {i.status:<9} {preis:>8} € (min {grenze}) {tage:>5}  {i.url or i.fehler or ''}")


def cmd_angebot(args) -> None:
    konf = lade_konfiguration(Path(args.config))
    produkte = {p.id: p for p in lade_produkte(Path(args.produkte))}
    if args.produkt_id not in produkte:
        raise ValueError(f"Produkt '{args.produkt_id}' nicht in {args.produkte}")
    p = produkte[args.produkt_id]
    inserat = Speicher(konf.datenordner).hole(p.id, args.plattform or p.plattformen[0])
    preis = inserat.preis_aktuell if inserat and inserat.preis_aktuell else p.preis
    tage = (datetime.now() - inserat.online_seit).days if inserat and inserat.online_seit else 0
    b = bewerte_angebot(p, preis, args.betrag, tage)
    print(f"Angebot {args.betrag:.2f} € für {p.name} (aktuell {preis:.2f} €): "
          f"{b.aktion.upper()}{f' → {b.betrag:.2f} €' if b.betrag else ''} – {b.begruendung}")


def cmd_markieren(args) -> None:
    konf = lade_konfiguration(Path(args.config))
    speicher = Speicher(konf.datenordner)
    gefunden = [i for i in speicher.alle() if i.produkt_id == args.produkt_id]
    for i in gefunden:
        i.status = args.status
        speicher.speichere(i)
        print(f"{i.schluessel} → {args.status}")
    if not gefunden:
        print(f"Keine Angebote zu '{args.produkt_id}' gefunden.")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="verkaufsagent", description="Stellt Produkte auf Marktplätzen wie Crazyslip und Creamsi ein.")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--produkte", default="produkte.yaml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="befehl", required=True)

    s = sub.add_parser("plattformen", help="Bekannte Plattformen und ihren Einrichtungsstand anzeigen")
    s.set_defaults(f=cmd_plattformen)

    s = sub.add_parser("anmelden", help="Einmalig im Browser anmelden (Sitzung wird gespeichert)")
    s.add_argument("plattform")
    s.set_defaults(f=cmd_anmelden)

    s = sub.add_parser("einrichten", help="Angebotsformular einer Plattform im Browser anlernen")
    s.add_argument("plattform")
    s.set_defaults(f=cmd_einrichten)

    s = sub.add_parser("login", help="Automatische Anmeldung einrichten (Zugangsdaten im Mac-Schlüsselbund)")
    s.add_argument("plattform")
    s.set_defaults(f=cmd_login)

    s = sub.add_parser("zugang", help="Nur Benutzername/Passwort für die automatische Anmeldung neu speichern")
    s.add_argument("plattform")
    s.set_defaults(f=cmd_zugang)

    s = sub.add_parser("texte", help="Titel/Beschreibungen erzeugen und anzeigen (ohne zu inserieren)")
    s.add_argument("produkt", nargs="*")
    s.add_argument("--neu", action="store_true", help="Texte neu erzeugen")
    s.set_defaults(f=cmd_texte)

    s = sub.add_parser("inserieren", help="Neue Produkte einstellen")
    s.add_argument("produkt", nargs="*")
    s.set_defaults(f=cmd_inserieren)

    s = sub.add_parser("preise", help="Statistik lesen und Preise ggf. reduzieren")
    s.set_defaults(f=cmd_preise)

    s = sub.add_parser("lauf", help="Einstellen + Preispflege (für Cronjob)")
    s.add_argument("--dauerbetrieb", action="store_true")
    s.add_argument("--intervall-h", type=float, default=12)
    s.set_defaults(f=cmd_lauf)

    s = sub.add_parser("status", help="Übersicht aller Angebote")
    s.set_defaults(f=cmd_status)

    s = sub.add_parser("angebot", help="Käuferangebot bewerten")
    s.add_argument("produkt_id")
    s.add_argument("betrag", type=float)
    s.add_argument("--plattform", help="Standard: erste Plattform des Produkts")
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
    except Exception as e:
        if "closed" in str(e).lower():
            sys.exit("Das Browserfenster wurde geschlossen. Bitte das Browserfenster offen lassen, bis das Terminal "
                     "fertig meldet. Bisher Gelerntes ist gespeichert – einfach noch einmal starten.")
        raise
