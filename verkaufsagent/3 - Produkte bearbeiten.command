#!/bin/bash
# Doppelklick: öffnet die Produktliste und den Foto-Ordner.
cd "$(dirname "$0")" || exit 1
[ -f produkte.yaml ] || { echo "Bitte zuerst '1 - Installieren' doppelklicken."; read -r -p "Enter zum Schließen … " _; exit 1; }
mkdir -p fotos
open -e produkte.yaml
open fotos
exit 0
