#!/bin/bash
# Doppelklick: startet den Agenten. Fenster offen lassen – er arbeitet selbstständig.
cd "$(dirname "$0")" || exit 1
clear
[ -x .venv/bin/python ] || { echo "Bitte zuerst '1 - Installieren' doppelklicken."; read -r -p "Enter zum Schließen … " _; exit 1; }
[ -f .api-schluessel ] && export ANTHROPIC_API_KEY="$(cat .api-schluessel)"
echo "=== Verkaufsagent läuft ==="
echo "Er stellt neue Produkte ein und prüft alle 12 Stunden die Preise."
echo "Dieses Fenster offen lassen. Beenden: Fenster schließen."
echo
.venv/bin/python -m verkaufsagent status
echo
.venv/bin/python -m verkaufsagent lauf --dauerbetrieb --intervall-h 12
read -r -p "Agent beendet. Enter zum Schließen … " _
