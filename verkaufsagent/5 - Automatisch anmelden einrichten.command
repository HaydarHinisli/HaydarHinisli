#!/bin/bash
# Doppelklick: bringt dem Agenten bei, sich selbst anzumelden (Passwort im Mac-Schlüsselbund).
cd "$(dirname "$0")" || exit 1
clear
[ -x .venv/bin/python ] || { echo "Bitte zuerst '1 - Installieren' doppelklicken."; read -r -p "Enter zum Schließen … " _; exit 1; }
echo "=== Automatische Anmeldung einrichten ==="
echo
echo "Welche Plattform?"
echo "  1) Crazyslip"
echo "  2) Creamsi"
echo "  3) Panty.com"
read -r -p "Zahl eingeben und Enter: " WAHL
case "$WAHL" in
  1) P=crazyslip ;; 2) P=creamsi ;; 3) P=panty ;;
  *) echo "Ungültige Auswahl."; read -r -p "Enter zum Schließen … " _; exit 1 ;;
esac
echo
echo "Gleich öffnet sich der Agent-Browser. Folge den Anweisungen hier im Fenster."
echo "Das Browserfenster NICHT schließen, bis hier 'Enter zum Schließen' steht."
.venv/bin/python -m verkaufsagent login "$P"
echo
read -r -p "Enter zum Schließen … " _
