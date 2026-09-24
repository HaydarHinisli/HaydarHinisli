#!/bin/bash
# Doppelklick: holt die neueste Version des Agenten in DIESEN Ordner.
# Deine Produkte, Fotos, Einstellungen und angelernten Plattformen bleiben erhalten.
cd "$(dirname "$0")" || exit 1
clear
echo "=== Verkaufsagent aktualisieren ==="
REPO="HaydarHinisli/HaydarHinisli"
ZWEIG="claude/product-listing-agent-bto71x"
SHA=$(curl -fsSL "https://api.github.com/repos/$REPO/commits/$ZWEIG" \
      | /usr/bin/python3 -c 'import sys, json; print(json.load(sys.stdin)["sha"])' 2>/dev/null)
if [ -z "$SHA" ]; then
  echo "Keine Verbindung zu GitHub – bitte später noch einmal versuchen."
  read -r -p "Enter zum Schließen … " _; exit 1
fi
TMP=$(mktemp -d)
if ! curl -fsSL -o "$TMP/neu.zip" "https://github.com/$REPO/archive/$SHA.zip" || ! unzip -q "$TMP/neu.zip" -d "$TMP"; then
  echo "Download fehlgeschlagen – bitte später noch einmal versuchen."
  read -r -p "Enter zum Schließen … " _; exit 1
fi
rsync -a --exclude daten --exclude fotos --exclude produkte.yaml --exclude config.yaml \
      --exclude .venv --exclude .api-schluessel "$TMP/HaydarHinisli-$SHA/verkaufsagent/" ./
rm -rf "$TMP"
chmod +x ./*.command
if [ -x .venv/bin/python ]; then
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi
echo "✔ Aktualisiert auf Version ${SHA:0:7}"
read -r -p "Enter zum Schließen … " _
