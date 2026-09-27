"""Modellanbindung. Die KI bekommt Text und liefert JSON – sie hat keine Werkzeuge.

Backends:
- ``claude_code``: ruft lokal ``claude -p`` auf (Anmeldung über das Claude-Abo),
  mit ausgeschalteten Werkzeugen, ohne MCP-Server, ohne Projekt-Einstellungen,
  in einem leeren temporären Verzeichnis.
- ``anthropic_api``: vorgesehen für Phase 3, bis zur Budgetfreigabe gesperrt.
- ``fake``: für Tests.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable


class ModelError(Exception):
    pass


class UsageLimitReached(ModelError):
    """Nutzungslimit des Abos erreicht – Sitzung pausieren, später fortsetzen."""


@dataclass
class ModelResult:
    data: dict
    raw_text: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cost_usd_equiv: float | None = None
    duration_ms: int = 0
    extra: dict = field(default_factory=dict)


# Umgebungsvariablen, die Claude Code auf nutzungsabhängige Abrechnung umstellen würden.
_BILLING_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
                "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")

_LIMIT_PATTERNS = re.compile(
    r"usage limit|limit reached|limit will reset|rate limit|5-hour limit|weekly limit|out of extra usage",
    re.I,
)
_AUTH_PATTERNS = re.compile(r"not logged in|please run /login|invalid api key|authentication", re.I)


class ClaudeCodeClient:
    backend = "claude_code"

    def __init__(self, cfg_model: dict):
        self.command = cfg_model.get("claude_code_command", "claude")
        self.model = cfg_model.get("claude_code_model", "opus")
        self.timeout = int(cfg_model.get("call_timeout_seconds", 600))
        # Strukturierte Ausgabe über --json-schema; falls das mit abgeschalteten Werkzeugen nicht
        # funktioniert (lernloop doctor --test-call prüft das), auf false setzen – dann wird das
        # JSON aus dem Antworttext gelesen und vom Programm geprüft.
        self.use_json_schema = bool(cfg_model.get("claude_code_json_schema", True))

    def available(self) -> str | None:
        return shutil.which(self.command)

    def build_args(self, system: str, schema: dict | None) -> list[str]:
        args = [
            self.command, "-p",
            "--output-format", "json",
            "--model", self.model,
            "--tools", "",
            "--strict-mcp-config",
            "--setting-sources", "user",
            "--no-session-persistence",
            "--system-prompt", system,
        ]
        if schema is not None and self.use_json_schema:
            args += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
        return args

    def complete(self, system: str, prompt: str, schema: dict | None, step: str) -> ModelResult:
        if schema is not None and not self.use_json_schema:
            prompt += "\n\nAntworte ausschließlich mit einem JSON-Objekt nach diesem Schema:\n" + json.dumps(
                schema, ensure_ascii=False)
        exe = self.available()
        if not exe:
            raise ModelError(
                f"'{self.command}' nicht gefunden. Claude Code installieren und mit dem Abo anmelden "
                "(siehe README, Abschnitt Einrichtung)."
            )
        env = {k: v for k, v in os.environ.items() if k not in _BILLING_ENV}
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="lernloop-claude-") as workdir:
            try:
                proc = subprocess.run(
                    self.build_args(system, schema), input=prompt, capture_output=True, text=True,
                    encoding="utf-8", timeout=self.timeout, cwd=workdir, env=env,
                )
            except subprocess.TimeoutExpired as exc:
                raise ModelError(f"Zeitüberschreitung nach {self.timeout}s") from exc
        duration = int((time.monotonic() - started) * 1000)
        return parse_claude_output(proc.returncode, proc.stdout, proc.stderr, duration)


def parse_claude_output(returncode: int, stdout: str, stderr: str, duration_ms: int) -> ModelResult:
    try:
        payload = json.loads(stdout) if stdout.strip() else None
    except json.JSONDecodeError:
        payload = None
    text_for_errors = " ".join(filter(None, [stdout[-2000:], stderr[-2000:]]))
    if payload is None or not isinstance(payload, dict):
        if _LIMIT_PATTERNS.search(text_for_errors):
            raise UsageLimitReached(text_for_errors.strip()[:500])
        if _AUTH_PATTERNS.search(text_for_errors):
            raise ModelError("Claude Code ist nicht angemeldet. Einmal `claude` starten und mit dem Abo anmelden.")
        raise ModelError(f"Unerwartete Ausgabe von Claude Code (Exit {returncode}): {text_for_errors[:500]}")
    result_text = payload.get("result") or ""
    if payload.get("is_error") or returncode != 0:
        msg = result_text or text_for_errors
        if _LIMIT_PATTERNS.search(msg):
            raise UsageLimitReached(msg.strip()[:500])
        if _AUTH_PATTERNS.search(msg):
            raise ModelError("Claude Code ist nicht angemeldet. Einmal `claude` starten und mit dem Abo anmelden.")
        raise ModelError(f"Claude Code meldet einen Fehler: {msg[:500]}")
    data = payload.get("structured_output")
    if not isinstance(data, dict):
        data = extract_json(result_text)
    usage = payload.get("usage") or {}
    models = list((payload.get("modelUsage") or {}).keys())
    return ModelResult(
        data=data,
        raw_text=result_text if result_text else json.dumps(data, ensure_ascii=False),
        model=",".join(models) or None,
        input_tokens=_int(usage.get("input_tokens")) + _int(usage.get("cache_creation_input_tokens")),
        output_tokens=_int(usage.get("output_tokens")),
        cache_read_tokens=_int(usage.get("cache_read_input_tokens")),
        cost_usd_equiv=payload.get("total_cost_usd"),
        duration_ms=duration_ms,
    )


def _int(v) -> int:
    return int(v) if isinstance(v, (int, float)) else 0


def extract_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ModelError("Antwort enthält kein JSON-Objekt")
    try:
        data = json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ModelError(f"Ungültiges JSON in der Antwort: {exc}") from exc
    if not isinstance(data, dict):
        raise ModelError("Antwort ist kein JSON-Objekt")
    return data


class ApiClient:
    backend = "anthropic_api"

    def __init__(self, cfg_api: dict):
        self.enabled = bool(cfg_api.get("paid_calls_enabled"))

    def complete(self, system, prompt, schema, step):
        if not self.enabled:
            raise ModelError("API-Aufrufe sind ausgeschaltet (api.paid_calls_enabled = false, Entscheidung E2).")
        raise ModelError("Die API-Anbindung wird vor Phase 3 umgesetzt; bis dahin backend = \"claude_code\".")


class FakeClient:
    """Test-Backend: eine Funktion (step, prompt, schema) -> dict liefert die Antworten."""

    backend = "fake"

    def __init__(self, responder: Callable[[str, str, dict | None], dict]):
        self.responder = responder
        self.calls: list[tuple[str, str]] = []

    def complete(self, system, prompt, schema, step):
        self.calls.append((step, prompt))
        data = self.responder(step, prompt, schema)
        return ModelResult(data=data, raw_text=json.dumps(data, ensure_ascii=False), model="fake",
                           input_tokens=len(prompt) // 4, output_tokens=50)


def make_client(cfg) -> object:
    backend = cfg.section("model")["backend"]
    if backend == "claude_code":
        return ClaudeCodeClient(cfg.section("model"))
    if backend == "anthropic_api":
        return ApiClient(cfg.section("api"))
    raise ModelError(f"Backend {backend} kann nicht direkt erzeugt werden")


# --- minimale JSON-Schema-Prüfung (nur die hier genutzten Konstrukte) ---------------------

def validate(schema: dict, data, path: str = "$") -> list[str]:
    errors: list[str] = []
    t = schema.get("type")
    types = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float)}
    if t:
        expected = types[t]
        if t in ("integer", "number") and isinstance(data, bool) or not isinstance(data, expected):
            return [f"{path}: erwartet {t}"]
    if "enum" in schema and data not in schema["enum"]:
        errors.append(f"{path}: Wert nicht erlaubt ({data!r})")
    if t == "object":
        for key in schema.get("required", []):
            if key not in data:
                errors.append(f"{path}.{key}: fehlt")
        for key, sub in schema.get("properties", {}).items():
            if key in data and data[key] is not None:
                errors.extend(validate(sub, data[key], f"{path}.{key}"))
    if t == "array":
        if "maxItems" in schema and len(data) > schema["maxItems"]:
            errors.append(f"{path}: mehr als {schema['maxItems']} Einträge")
        for i, item in enumerate(data):
            errors.extend(validate(schema.get("items", {}), item, f"{path}[{i}]"))
    if t == "string" and "maxLength" in schema and len(data) > schema["maxLength"]:
        errors.append(f"{path}: länger als {schema['maxLength']} Zeichen")
    return errors
