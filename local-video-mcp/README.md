# local-video-mcp

Ein MCP-Server, mit dem ein **lokaler KI-Assistent** deine **eigene private Videosammlung
(18+)** auf deinem Rechner durchsuchen, taggen, bewerten und abspielen kann. MCP (Model Context
Protocol) ist der Plugin-Standard, den die meisten KI-Apps unterstützen.

- Der Server liest nur Metadaten: Dateiname, Ordner, optionale Beschreibung, Dauer. Die KI sieht
  keine Bilder und keine Videos.
- Der Index liegt als SQLite-Datei auf deinem Rechner. Es gibt keine Online-Quellen und kein
  Scraping.
- Solange du nicht per Konfiguration bestätigst, dass du volljährig bist, sind alle Werkzeuge
  gesperrt.

## Wo du das nutzen darfst

| KI-App | Geht das? |
|---|---|
| Lokale Modelle über **LM Studio, Jan, Open WebUI + Ollama, AnythingLLM, Msty …** | Ja. Alles bleibt auf deinem Rechner. |
| **Claude** (claude.ai, Claude Desktop, Claude Work) | **Nein.** Anthropics Nutzungsrichtlinie verbietet sexuell explizite Inhalte. |
| **ChatGPT** | **Nein.** Laut OpenAIs Richtlinien für Apps nicht erlaubt. |
| Andere Cloud-KIs | Nur wenn deren Nutzungsbedingungen das ausdrücklich erlauben. Titel und Tags gehen dann an den Anbieter. |

Verwende nur Inhalte, die du legal besitzt und die ausschließlich einvernehmlich handelnde
Erwachsene zeigen.

## Installation

Du brauchst Python 3.10 oder neuer. Optional sind:

- **ffmpeg** (enthält `ffprobe`), damit die Videolänge angezeigt wird;
- **mpv** oder **VLC** zum Abspielen. Ohne diese Programme wird der Standard-Player des
  Systems verwendet.

```bash
pipx install ./local-video-mcp          # oder: pip install ./local-video-mcp
local-video-mcp --help
```

Danach gibt es den Befehl `local-video-mcp`. Falls deine KI-App ihn nicht findet, trag in der
Konfiguration den vollständigen Pfad ein. Den zeigt dir `which local-video-mcp`, unter Windows
`where local-video-mcp`.

## Konfiguration

Die Einstellungen kommen über Umgebungsvariablen. In den KI-Apps trägst du sie im `env`-Block
ein.

| Variable | Bedeutung | Standard |
|---|---|---|
| `VIDEO_LIBRARY_PATHS` | Ordner mit deinen Videos, getrennt durch `:` (Linux/macOS) bzw. `;` (Windows) | — (Pflicht) |
| `VIDEO_AGE_CONFIRMED` | `true` = „Ich bin mindestens 18 Jahre alt“. Ohne diesen Wert ist alles gesperrt. | `false` |
| `VIDEO_PLAYER` | Player-Befehl, z. B. `mpv --fs` oder `"C:\Program Files\VideoLAN\VLC\vlc.exe"` | `auto` (mpv → VLC → System) |
| `VIDEO_DB_PATH` | Speicherort des Index | `~/.local/share/local-video-mcp/library.db` bzw. `%LOCALAPPDATA%\local-video-mcp\library.db` |
| `VIDEO_PROBE_DURATION` | Videolänge mit `ffprobe` auslesen (`false` macht den ersten Scan großer Sammlungen schneller) | `true` |

Beim ersten Aufruf durch die KI wird die Sammlung automatisch indexiert. Große Sammlungen
kannst du vorher selbst indexieren:

```bash
VIDEO_LIBRARY_PATHS=/pfad/zu/videos local-video-mcp scan
```

### Sammlung organisieren

- **Ordner werden zu Tags.** `Videos/Favoriten/2024/clip.mp4` bekommt die Tags `favoriten`
  und `2024`.
- **Titel** entstehen aus dem Dateinamen (`Mein_Clip.Teil.1.mp4` → „Mein Clip Teil 1“).
- **Optional eine Sidecar-Datei** mit gleichem Namen und der Endung `.json` neben dem Video:

  ```json
  { "title": "Eigener Titel", "description": "Kurze Notiz", "tags": ["lang", "hd"] }
  ```

- Tags und Bewertungen, die du über die KI vergibst, bleiben bei jedem neuen Scan erhalten.
  Das gilt auch, wenn eine externe Festplatte gerade nicht angeschlossen ist.

## In deiner KI-App einrichten

Das Modell muss **Tool-Calling** können, zum Beispiel Qwen 2.5/3, Llama 3.1+ oder Mistral.

### LM Studio, Jan, AnythingLLM, Msty und andere Desktop-Apps (stdio)

Füge in der MCP-Konfiguration der App (bei LM Studio `mcp.json`) diesen Eintrag hinzu:

```json
{
  "mcpServers": {
    "videos": {
      "command": "local-video-mcp",
      "env": {
        "VIDEO_LIBRARY_PATHS": "/home/du/Videos/Privat",
        "VIDEO_AGE_CONFIRMED": "true"
      }
    }
  }
}
```

Unter Windows sieht der Pfad so aus: `"VIDEO_LIBRARY_PATHS": "D:\\Videos\\Privat;E:\\Extern"`.
Die doppelten Backslashes sind in JSON Pflicht.

### Open WebUI (Streamable HTTP)

```bash
VIDEO_LIBRARY_PATHS=/home/du/Videos/Privat VIDEO_AGE_CONFIRMED=true \
  local-video-mcp serve --transport http --port 8765
```

Füge dann in Open WebUI unter den Admin-Einstellungen bei den externen Tools einen
MCP-Server (Streamable HTTP) mit der URL `http://127.0.0.1:8765/mcp` hinzu.

Läuft Open WebUI in Docker, kann es `127.0.0.1` des Hosts nicht erreichen. Starte den Server
dann mit `--host 0.0.0.0` und verwende `http://host.docker.internal:8765/mcp`. Der Server hat
**keinen Login**, also darf dieser Port nicht aus dem Internet oder dem restlichen Netzwerk
erreichbar sein.

## Werkzeuge für die KI

| Tool | Funktion |
|---|---|
| `search_videos` | Suche nach Wörtern in Titel, Beschreibung und Tags; Filter nach Tags und Mindestbewertung; Sortierung (neueste, älteste, Titel, Bewertung, Länge, zufällig) mit Seiten |
| `random_video` | Zufälliges Video, optional nur mit bestimmten Tags |
| `get_video` | Details inklusive Dateipfad |
| `play_video` | Öffnet das Video im Player auf deinem Rechner |
| `tag_video` | Eigene Tags hinzufügen oder entfernen |
| `rate_video` | 1–5 Sterne vergeben oder löschen |
| `list_tags` | Alle Tags mit Anzahl |
| `library_stats` | Anzahl der Videos, Größe, Gesamtdauer, letzter Scan |
| `scan_library` | Neu indexieren, wenn Dateien hinzugekommen oder verschoben wurden |

Beispiele:
- „Zeig mir meine 5 bestbewerteten Videos mit dem Tag favoriten.“
- „Spiel irgendwas Zufälliges aus 2024 ab.“
- „Gib dem letzten Video 4 Sterne und den Tag ‚nochmal‘.“

## Entwicklung

```bash
cd local-video-mcp
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```
