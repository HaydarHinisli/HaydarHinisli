"""Red-team hardening (docs/DECISIONS.md ADR-064): two small, deliberately
in-memory guards for the real-call browser test path (ADR-060/061/062/063) —

1. `VoiceTicketLedger` — a voice_call_ticket's own replay/reuse detection.
   Ticket verification (signature/expiry/purpose/call ownership,
   app/auth/security.py) proves a ticket is genuine and still current, but
   cannot by itself distinguish "Twilio retried the exact same call-setup
   request" (must be treated identically/idempotently — Twilio's own
   documented retry behavior must never break a legitimate call) from "this
   exact ticket is being reused to start a SECOND, independent real call"
   (must fail closed — this is the actual replay risk). The one fact that
   tells them apart is Twilio's own `CallSid`: retried deliveries of the same
   call-setup attempt always carry the SAME CallSid (Twilio allocates it once
   per attempt, before ever requesting TwiML); a genuinely new attempt gets a
   new one. See `VoiceTicketLedger.check_and_record()`.

2. `VoiceCallConcurrencyLock` — at most one real test call in flight per
   REPLICA `call_id` at a time, independent of ticket identity (two
   DIFFERENT, both individually valid tickets for the same call_id — e.g.
   from two browser tabs — must not both be allowed to place a real call and
   attach a Media Stream to the same call_id concurrently).

Both are deliberately in-memory and single-instance-scoped, matching this
pilot's already-documented deployment constraint for the exact same reason
`app/services/live_push.LiveSuggestionHub` is (see docs/DEPLOYMENT.md) — this
is the manual, one-operator-at-a-time real-call test path, not a scaled
product feature, and a DB-backed ledger for it would be new infrastructure
this pass was explicitly asked not to add.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field

# How long a ticket's (jti -> CallSid) mapping is remembered — comfortably
# longer than a voice_call_ticket's own max lifetime (5 minutes default), so
# a legitimate retry is never mistaken for a "never seen this jti" case just
# because the ledger already forgot it; pruned lazily, not by a background task.
_TICKET_RECORD_TTL_S = 900

# Safety-net only for the concurrency lock below — the real release path is
# explicit (the call's Media Stream ending, app/main.py's /ws/twilio-media).
# Long enough to cover any realistic single real test call; short enough that
# a stuck lock (the Media Stream never even connects after TwiML is returned)
# self-heals without requiring a server restart.
_CALL_LOCK_TTL_S = 1800


@dataclass
class _TicketUse:
    call_sid: str
    recorded_at_monotonic: float


@dataclass
class VoiceTicketLedger:
    _uses: dict[str, _TicketUse] = field(default_factory=dict)

    def _prune(self, now: float) -> None:
        stale = [jti for jti, use in self._uses.items() if now - use.recorded_at_monotonic > _TICKET_RECORD_TTL_S]
        for jti in stale:
            self._uses.pop(jti, None)

    def check_and_record(self, *, jti: str, call_sid: str) -> str:
        """Returns:
        - `'new'` — first time this ticket (jti) has ever been used; the
          caller should proceed (and, for the concurrency lock above, this is
          the ONLY verdict that should ever attempt to acquire it — a
          `'retry'` is already covered by whatever the original attempt did).
        - `'retry'` — this exact ticket was already used for a call attempt
          with this SAME Twilio CallSid — a legitimate provider retry of the
          same delivery; the caller should behave identically (return the
          same TwiML again), never reject it.
        - `'conflict'` — this exact ticket was already used for a DIFFERENT
          CallSid — a second, independent real-call attempt reusing one
          ticket; the caller must fail closed.
        """
        now = time.monotonic()
        self._prune(now)
        existing = self._uses.get(jti)
        if existing is None:
            self._uses[jti] = _TicketUse(call_sid=call_sid, recorded_at_monotonic=now)
            return 'new'
        if existing.call_sid == call_sid:
            return 'retry'
        return 'conflict'


@dataclass
class VoiceCallConcurrencyLock:
    _held: dict[int, float] = field(default_factory=dict)

    def _locked_and_current(self, call_id: int, now: float) -> bool:
        expires_at = self._held.get(call_id)
        return expires_at is not None and now < expires_at

    def try_acquire(self, *, call_id: int, ttl_seconds: float = _CALL_LOCK_TTL_S) -> bool:
        """Returns False (refuse) if a real call is already believed to be in
        flight for this call_id; otherwise acquires the lock and returns True."""
        now = time.monotonic()
        if self._locked_and_current(call_id, now):
            return False
        self._held[call_id] = now + ttl_seconds
        return True

    def release(self, *, call_id: int) -> None:
        self._held.pop(call_id, None)

    def is_locked(self, *, call_id: int) -> bool:
        return self._locked_and_current(call_id, time.monotonic())


_ticket_ledger = VoiceTicketLedger()
_call_lock = VoiceCallConcurrencyLock()


def get_voice_ticket_ledger() -> VoiceTicketLedger:
    return _ticket_ledger


def get_voice_call_lock() -> VoiceCallConcurrencyLock:
    return _call_lock
