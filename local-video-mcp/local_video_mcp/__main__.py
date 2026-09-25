"""Command line entry point: `local-video-mcp [serve|scan]`."""

from __future__ import annotations

import argparse
import json
import sys

from .config import Config
from .library import Library

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="local-video-mcp",
        description="MCP server for a private local video library. Configured via VIDEO_* environment variables.",
    )
    parser.set_defaults(command="serve", transport="stdio", host="127.0.0.1", port=8765)
    commands = parser.add_subparsers(dest="command")

    serve = commands.add_parser("serve", help="run the MCP server (default)")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                       help="stdio for desktop clients, http (Streamable HTTP) for web UIs like Open WebUI")
    serve.add_argument("--host", default="127.0.0.1", help="http only; keep 127.0.0.1 unless you know why")
    serve.add_argument("--port", type=int, default=8765, help="http only")

    commands.add_parser("scan", help="index the library folders and print a summary")

    args = parser.parse_args(argv)
    try:
        config = Config.from_env()
    except ValueError as exc:
        parser.error(str(exc))

    if args.command == "scan":
        if not config.library_paths:
            print("VIDEO_LIBRARY_PATHS is not set.", file=sys.stderr)
            return 2
        result = Library(config.db_path).scan(config.library_paths, probe_duration=config.probe_duration)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0

    # Imported here so `scan` works without loading the MCP stack.
    from .server import build_server

    server = build_server(config)
    if args.transport == "http":
        if args.host not in _LOOPBACK_HOSTS:
            print(
                f"Warning: listening on {args.host}. Anyone who can reach this port can browse "
                "and play your library; there is no login.",
                file=sys.stderr,
            )
        server.run("streamable-http", host=args.host, port=args.port)
    else:
        server.run("stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
