"""Speaker-Role-Mapping resolver (Sprint 2B, docs/DECISIONS.md ADR-043).

Twilio's `inbound`/`outbound` track labels are a TRANSPORT-level concept — "audio
coming into Twilio from the far end of the call" / "audio Twilio is sending to the
far end" — not a business-level concept. They must never be silently equated with
`prospect`/`seller` as a hardcoded, universal fact: which physical track carries
which speaking role depends entirely on the call's telephony topology (who is
bridged onto the call, and how), and that topology can vary from Twilio account
config to call flow to future feature. Assuming `inbound == prospect` unconditionally
would silently mislabel every turn the moment topology changes (e.g. an inbound
lead-response flow instead of outbound cold-calling, or a conference bridge with a
different leg order).

This module makes that mapping an explicit, injectable, testable step instead of a
constant baked into TurnDetector. Exactly one resolver exists today,
`OutboundSalesFlowResolver`, and it is scoped deliberately narrowly: it is only
correct for REPLICA's own defined outbound cold-calling flow, where the seller's
call to the prospect is placed via Twilio and the seller's own voice is bridged onto
that same call leg (e.g. via `<Dial>` connecting the seller's device) so that:
- `inbound` = audio arriving at Twilio FROM the far end of the PSTN call = the PROSPECT.
- `outbound` = audio Twilio sends TO the far end = whatever REPLICA/the seller's leg
  contributes onto the call = the SELLER (human, today; the same track would carry
  an AI agent's TTS output in a future speaker_mode, still resolved to a
  non-prospect role by this same resolver — see `AI_AGENT_SPEAKER_MODES` handling
  below).

Any OTHER call topology (inbound lead-response, conference bridges with more than
two parties, warm transfers, ...) is explicitly OUT OF SCOPE for this resolver and
must not be assumed to work — see docs/DECISIONS.md ADR-043 for the full topology
restriction and what would need to change to support another one.
"""
from __future__ import annotations
from typing import Protocol

from .media_stream_session import INBOUND, OUTBOUND


class SpeakerRoleResolver(Protocol):
    def resolve(self, track: str) -> str:
        """Returns 'prospect' or 'seller' (or another domain role) for a given
        Twilio track name, given this resolver's assumed call topology."""
        ...


class OutboundSalesFlowResolver:
    """The only resolver implemented today. Correct ONLY for REPLICA's defined
    outbound sales call flow (see module docstring) — one prospect leg (`inbound`)
    and one seller/agent leg (`outbound`), no additional parties on the bridge.
    """
    TOPOLOGY_NAME = 'outbound_sales_flow_v1'

    def resolve(self, track: str) -> str:
        if track == INBOUND:
            return 'prospect'
        if track == OUTBOUND:
            return 'seller'
        return track  # unrecognized track name — surfaced as-is, never guessed


def get_default_speaker_role_resolver() -> SpeakerRoleResolver:
    """Seam entry point (mirrors app/secrets.get_secrets_provider() and
    app/streaming/asr.get_asr_provider()'s pattern): today always returns the one
    supported topology's resolver. A future call topology gets its own resolver
    class and a way to select it here — never a second hardcoded mapping scattered
    into TurnDetector or elsewhere."""
    return OutboundSalesFlowResolver()
