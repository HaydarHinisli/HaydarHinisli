#!/usr/bin/env python3
"""Startpunkt für den MCP-Server „make-wissen“.

Wird von Claude Code / Claude Desktop gestartet (Einrichtung: `python3 -m lernloop mcp-install`).
Findet Programm und Konfiguration relativ zu seinem eigenen Ort – egal, aus welchem Ordner
Claude gestartet wird.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from lernloop.cli import main  # noqa: E402

sys.exit(main(["--config", str(HERE / "lernloop.toml"), "mcp"]))
