# REPLICA — Developer Handoff / MVP

REPLICA ist ein **Adaptive Sales Intelligence System** für telefonischen Vertrieb. Der erste Produktkern ist kein autonomer Cold Caller, sondern ein **Live-Copilot + Post-Call-Coach + Manager-Intelligence-Layer**.

Der Ordner enthält zwei Dinge gleichzeitig:

1. **einen lokal lauffähigen MVP**, der den Produktkern demonstriert;
2. **eine vollständige Handoff-Spezifikation**, mit der ein Entwickler den Pilot produktionsnah fertigbauen kann.

## Was der MVP bereits zeigt

- Live-Copilot: Prospect-Aussage → Einwand/Sales-Event → sprachlicher Stil → kurze nächste Antwort
- LanguageSync: einfache vs. komplexere Sprache, Direktheit, Spiegelbegriffe
- Consent Gate: Live-/Turn-Analyse wird ohne dokumentierte Zustimmung blockiert
- Turn-/Call-Speicherung
- akustische Messfelder im Datenmodell: WPM, Response Latency, Pause, Overlap, Loudness, Pitch
- Reaction-Delta-Service: relative Veränderung gegen Prospect-Baseline
- Post-Call Review: Stärken, Verbesserungen, verpasste Chancen, nächster Fokus
- Manager Overview: Ergebnis + Ramp-up + Trend statt simplen „gut/schlecht“-Scores
- Meetings/Deals als Downstream-Outcomes
- Experiment Engine für deterministische A/B-Zuordnung
- Revenue Reward Layer
- HubSpot-, Google-Calendar- und Salesforce-Adapter
- Twilio Media Streams WebSocket-Eingang
- OpenAI-Realtime-Integrationsnaht
- API-Dokumentation automatisch unter `/docs`

## Schnellstart lokal

```bash
cd replica-handoff
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
./run.sh
```

Dann öffnen:

- App: `http://127.0.0.1:8000`
- OpenAPI/Swagger: `http://127.0.0.1:8000/docs`

Tests:

```bash
pytest -q
```

## Wichtiger Hinweis zum MVP

Die Live-Empfehlungen kommen derzeit aus einem deterministischen **Fast Path**. Das ist absichtlich so: Damit kann der Entwickler UI, Datenmodell, Feedback-Loop und Latenzmessung bauen, ohne dass das Produkt schon von einem kostenpflichtigen Modell abhängt.

In Produktion wird daraus:

`Streaming ASR → Fast Classifier → LanguageSync → SalesBrain → (optional Smart LLM Path) → UI`

Der Smart Path darf den Fast Path ergänzen, aber nicht blockieren.

## Dateien für den Entwickler

- `docs/PRODUCT_SPEC.md` — Was genau gebaut werden soll
- `docs/ARCHITECTURE.md` — Zielarchitektur und Latenzpfad
- `docs/DATA_MODEL.md` — Datenmodell / Cold Call Genome
- `docs/API_SPEC.md` — API-Kontrakte
- `docs/INTEGRATIONS.md` — Twilio, OpenAI Realtime, CRM, Kalender
- `docs/PILOT_AND_METRICS.md` — Pilotdesign und Erfolgsmessung
- `docs/SECURITY_PRIVACY.md` — Mandantentrennung, Consent, Lernmodi
- `docs/CODER_HANDOFF.md` — konkrete Sprint-Reihenfolge / Definition of Done
- `config/prompts.yaml` — Prompt-Verträge für den späteren Smart Path

## Produktprinzipien

1. **Human-in-the-loop first.** Der Verkäufer entscheidet, nicht REPLICA.
2. **Keine Emotionserkennung behaupten.** Gemessen werden beobachtbare Signale, z. B. Antwortlatenz, WPM, Pausen und Wortwahl.
3. **Keine automatische Personalentscheidung.** Manager erhalten Kontext und Coaching-Signale, keine Kündigungs-/Eignungsempfehlung.
4. **Private Learning by default.** Kundendaten trainieren nicht automatisch ein globales Modell.
5. **Outcome > Vanity Metrics.** Held Meeting / Opportunity / Revenue sind wichtiger als reine Meeting-Bookings.
6. **Fast Path first.** Live-Vorschläge müssen schnell und kurz sein.

## Produktionslücken, die ein Entwickler schließen muss

- OAuth statt statischer Tokens
- echtes Multi-Tenant-Auth/RBAC
- PostgreSQL + Migrationen/RLS
- Streaming-ASR mit Interim Transcripts
- reale Turn-End-Erkennung
- Audio-Feature-Extraktion
- UI-Push via WebSocket/SSE
- echte Suggestion-Latency-Messung vom Prospect-Turn-Ende bis Render
- CRM/Calendar-Sync-Jobs + Webhooks
- Observability, Rate Limits, Retry/Idempotency
- Security Review, DPIA/Datenschutzkonzept, Verträge

## Empfohlener Pilotumfang

Ein Verkäufer, ein Angebot, eine Zielgruppe, 4–6 Wochen. Erst wenn Live-Vorschläge zuverlässig genutzt werden und eine positive Tendenz bei qualifizierten Outcomes erkennbar ist, sollte der autonome Voice-Agent gebaut werden.

## Global rollout / legal-product guardrails

Before production work, developers must read:
- `docs/GLOBAL_PRODUCT_COMPLIANCE_SPEC.md`
- `config/jurisdictions.yaml`

These define runtime feature gating for recording, autonomous voice, employee analytics and cross-company Network Intelligence.
