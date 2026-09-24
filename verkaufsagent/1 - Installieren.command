#!/bin/bash
# Doppelklick: installiert den Verkaufsagenten (einmalig).
cd "$(dirname "$0")" || exit 1
clear
echo "=== Verkaufsagent: Installation ==="
echo

# Python 3.10+ nötig
PY=""
for kandidat in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$kandidat" >/dev/null 2>&1 && "$kandidat" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    PY="$kandidat"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.10 oder neuer fehlt."
  echo "Die Download-Seite öffnet sich jetzt: bitte den 'macOS installer' laden und installieren."
  echo "Danach diese Datei noch einmal doppelklicken."
  open "https://www.python.org/downloads/macos/"
  read -r -p "Enter zum Schließen … " _
  exit 1
fi
echo "✔ Python gefunden: $($PY --version)"

echo "… Programmteile werden installiert (dauert ein paar Minuten)"
"$PY" -m venv .venv || { read -r -p "Fehler bei der Installation. Enter zum Schließen … " _; exit 1; }
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt || { read -r -p "Fehler bei der Installation. Enter zum Schließen … " _; exit 1; }
.venv/bin/python -m playwright install chromium || { read -r -p "Fehler beim Browser-Download. Enter zum Schließen … " _; exit 1; }
echo "✔ Programm installiert"

[ -f config.yaml ] || cp config.example.yaml config.yaml
[ -f produkte.yaml ] || cp produkte.example.yaml produkte.yaml
mkdir -p fotos/slip-001 fotos/bh-002   # Beispiel-Ordner aus produkte.yaml
echo "✔ Einstellungen angelegt"

echo
echo "Optional: Schlüssel für KI-Beschreibungen (von console.anthropic.com)."
echo "Einfügen und Enter drücken – oder nur Enter zum Überspringen:"
read -r SCHLUESSEL
if [ -n "$SCHLUESSEL" ]; then
  printf '%s' "$SCHLUESSEL" > .api-schluessel
  chmod 600 .api-schluessel
  echo "✔ Schlüssel gespeichert"
else
  echo "→ Ohne Schlüssel werden die Beschreibungen nach einer Vorlage geschrieben."
fi

echo
echo "=== Fertig! Weiter mit: '2 - Plattform einrichten' ==="
read -r -p "Enter zum Schließen … " _
