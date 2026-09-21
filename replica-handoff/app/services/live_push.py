"""Sprint 3A: Live Suggestion Push (docs/DECISIONS.md ADR-048).

In-process WebSocket delivery from the central streaming pipeline
(app/streaming/pipeline.py) to a connected seller's browser client
(`/ws/live/{call_id}` in app/main.py). A persisted Suggestion is handed to
`LiveSuggestionHub.publish_suggestion()` exactly once per finalized turn (the
pipeline's own `ProcessedTurnEvent` claim already guarantees that) — this module
does not add its own dedup ledger on top; it only guards against ever sending to
the wrong tenant.

Known limitation, documented rather than silently assumed away: this hub is an
in-process, in-memory registry. It works for a single REPLICA server process
(today's pilot deployment shape) but does NOT fan out across multiple server
instances — a seller connected to instance A never receives a push produced by
instance B. A multi-instance deployment would need a shared pub/sub backplane
(e.g. Redis) in front of this same publish/register interface; out of scope for
this pilot, tracked as tech debt. See `docs/DEPLOYMENT.md` for the exact
deployment-topology requirement this implies (single instance, or sticky routing
per call_id) — READ THAT before deploying this behind a load balancer.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field

from fastapi import WebSocket

logger = logging.getLogger('replica.live_push')

# Sprint 3A requirement 2: a presentational-only short guidance tag derived from
# SalesBrain's EXISTING `strategy` field — this is a UI label lookup, not a new
# SalesBrain classification/decision (no new sales logic is added in Sprint 3A).
# A strategy with no entry here simply gets no short hint (optional, at most one,
# per the explicit UI requirement) — never invented client-side either.
GUIDANCE_HINTS: dict[str, str] = {
    'permission_and_relevance': 'kurz',
    'qualify_email_request': 'weiterfragen',
    'separate_reflex_from_rejection': 'nicht argumentieren',
    'discover_buying_criteria': 'weiterfragen',
    'reestablish_value_before_price': 'Preis noch nicht verteidigen',
    'map_decision_process': 'weiterfragen',
    'answer_then_return_to_discovery': 'kurz',
    'advance_discovery': 'weiterfragen',
    'greeting_and_permission': 'kurz',
    'brief_social_reaction_then_prepare_transition': 'kurz',
    'transition_to_business': 'kurz',
    'trade_concessions_for_commitment': 'Preis noch nicht verteidigen',
    'confirm_and_close_politely': 'kurz',
}


def guidance_hint(strategy: str | None) -> str | None:
    if strategy is None:
        return None
    return GUIDANCE_HINTS.get(strategy)


@dataclass(eq=False)
class _Subscriber:
    """`eq=False` keeps default identity-based hashing so instances can live in a
    `set` even though two subscribers can otherwise compare equal-by-value."""
    websocket: WebSocket
    call_id: int
    company_id: int
    user_id: int


@dataclass
class LiveSuggestionHub:
    """Call_id-scoped in-memory WebSocket registry.

    Tenant isolation is enforced twice, deliberately redundantly: the WS endpoint
    only ever registers a subscriber with the company_id it already verified from
    that subscriber's OWN authenticated JWT (never client-supplied), and
    `publish_suggestion()` below re-checks that same company_id against every
    subscriber before sending — so a bug in either place alone still cannot cause
    a cross-tenant delivery.
    """
    _subscribers: dict[int, set[_Subscriber]] = field(default_factory=dict)
    _last_payload: dict[int, dict] = field(default_factory=dict)
    # Red-team hardening (docs/DECISIONS.md ADR-063, item 3): the pipeline/analysis
    # state (media stream / ASR / transcript / suggestion-pipeline health), tracked
    # and resynced on reconnect exactly like `_last_payload` above, but as its OWN
    # channel — a phone call being connected must never be conflated with REPLICA's
    # analysis actually working (see app/streaming/pipeline.py's PipelineStatus).
    _last_status: dict[int, dict] = field(default_factory=dict)

    def register(self, *, call_id: int, company_id: int, user_id: int, websocket: WebSocket) -> _Subscriber:
        sub = _Subscriber(websocket=websocket, call_id=call_id, company_id=company_id, user_id=user_id)
        self._subscribers.setdefault(call_id, set()).add(sub)
        return sub

    def unregister(self, sub: _Subscriber) -> None:
        subs = self._subscribers.get(sub.call_id)
        if subs is None:
            return
        subs.discard(sub)
        if not subs:
            self._subscribers.pop(sub.call_id, None)

    def subscriber_count(self, call_id: int) -> int:
        return len(self._subscribers.get(call_id, ()))

    def last_payload(self, call_id: int) -> dict | None:
        """Used for sync-on-connect: a reconnecting client is never left blank —
        it immediately gets the most recent suggestion for this call, if any.
        Deliberately NOT a backlog/queue of everything missed while disconnected
        (see module docstring's known-limitation note) — guidance is inherently
        "latest wins" once the conversation has moved on."""
        return self._last_payload.get(call_id)

    async def _send(self, *, call_id: int, company_id: int, message: dict) -> dict:
        """Shared tenant-checked fan-out used by `publish_suggestion()` and the
        pipeline-status/staleness pushes below — one send path, one place the
        cross-tenant check lives, rather than three copies that could drift out
        of sync with each other."""
        delivered = 0
        for sub in list(self._subscribers.get(call_id, ())):
            if sub.company_id != company_id:
                # Structurally unreachable given how register() is always called
                # (see class docstring) — kept as an explicit fail-closed check
                # rather than trusting that invariant silently.
                logger.error('live push: cross-tenant delivery blocked', extra={'fields': {'call_id': call_id}})
                continue
            try:
                await sub.websocket.send_json(message)
                delivered += 1
            except Exception as exc:  # noqa: BLE001 — one dead subscriber must not break the others or the caller
                logger.warning('live push: send failed, dropping subscriber', extra={'fields': {'call_id': call_id, 'error': str(exc)}})
                self.unregister(sub)
        return {'delivered_to': delivered}

    async def publish_suggestion(self, *, call_id: int, company_id: int, payload: dict) -> dict:
        """Hands `payload` to every currently-connected subscriber for this
        call_id whose OWN authenticated company_id matches `company_id`. Returns
        {'delivered_to': N} for logging/tests.

        Sprint 3A requirement 1: the CALLER treats this call itself — not the
        `delivered_to` count in its return value — as the moment the suggestion
        was "handed to the live-delivery layer" for `t_suggestion_pushed`. Zero
        connected subscribers (the seller's browser tab isn't open yet) is a
        legitimate outcome, not a failure to hand off: the persisted Suggestion
        genuinely was handed to this delivery layer, it simply had no one to
        deliver to at that instant.
        """
        self._last_payload[call_id] = {**payload, 'stale': False}
        return await self._send(call_id=call_id, company_id=company_id, message={'type': 'suggestion', **payload})

    async def push_status(self, *, call_id: int, company_id: int, status: str, detail: str | None = None) -> dict:
        """Red-team hardening (docs/DECISIONS.md ADR-063, item 3): pushes the
        pipeline/analysis-health state — deliberately a SEPARATE message type
        from `suggestion`, never conflated with it, so the browser can show "Call
        verbunden" (from the Twilio Voice SDK's own call state) and "Analyse
        nicht verfügbar" (from here) as the two genuinely independent facts they
        are. Remembered per call_id exactly like `_last_payload`, so a
        reconnecting seller's browser is resynced to the current analysis state,
        not left showing a stale/default one."""
        record = {'status': status, 'detail': detail}
        self._last_status[call_id] = record
        return await self._send(call_id=call_id, company_id=company_id, message={'type': 'pipeline_status', **record})

    def last_status(self, call_id: int) -> dict | None:
        return self._last_status.get(call_id)

    async def push_suggestion_stale(self, *, call_id: int, company_id: int, reason: str) -> dict:
        """Red-team hardening (docs/DECISIONS.md ADR-063, item 4): a runtime
        failure (Media-Stream/Deepgram disconnect, an untrusted speaker mapping,
        an unhandled pipeline exception) must never leave the seller's last-shown
        "Sag jetzt" suggestion looking as current/trustworthy as it did the
        instant before the failure. This does not retract or delete that
        suggestion (it may still be exactly right) — it marks it, visibly, as
        no longer backed by a confirmed-working analysis pipeline. Also updates
        the remembered last-payload's `stale` flag, so a client that reconnects
        AFTER this failure is resynced to the correct (stale) state too, not
        just one that was already connected when it happened."""
        last = self._last_payload.get(call_id)
        if last is not None:
            self._last_payload[call_id] = {**last, 'stale': True}
        return await self._send(call_id=call_id, company_id=company_id, message={'type': 'suggestion_stale', 'reason': reason})


_hub = LiveSuggestionHub()


def get_live_suggestion_hub() -> LiveSuggestionHub:
    return _hub
