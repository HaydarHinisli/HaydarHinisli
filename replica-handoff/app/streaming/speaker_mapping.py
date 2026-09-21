"""Speaker-Role-Mapping resolver (Sprint 2B, docs/DECISIONS.md ADR-043, mapping
corrected for the confirmed real test topology by ADR-053).

Twilio's `inbound`/`outbound` track labels are a TRANSPORT-level concept — "audio
coming into Twilio from the far end of the call" / "audio Twilio is sending to the
far end" — not a business-level concept. They must never be silently equated with
`prospect`/`seller` as a hardcoded, universal fact: which physical track carries
which speaking role depends entirely on the call's telephony topology (who is
bridged onto the call, and how), and that topology can vary from Twilio account
config to call flow to future feature. Assuming a fixed track means a fixed role
unconditionally would silently mislabel every turn the moment topology changes
(e.g. an inbound lead-response flow instead of outbound cold-calling, or a
conference bridge with a different leg order) — which is exactly what happened
once between ADR-043 and ADR-053: see ADR-053 for the full correction story and
why the direction below is now the reverse of ADR-043's original assumption.

This module makes that mapping an explicit, injectable, testable step instead of a
constant baked into TurnDetector. Exactly one resolver exists today,
`OutboundSalesFlowResolver`, and it is scoped deliberately narrowly: it is only
correct for REPLICA's own defined outbound cold-calling flow, as CONCRETELY
implemented for the first real test call (ADR-053): the seller calls REPLICA's
Twilio number (this becomes the PARENT call), TwiML executes `<Start><Stream
track="both_tracks">` followed by `<Dial>` to the consenting prospect test
person's number (this creates the DIALED-OUT child leg). On that parent call's
Media Stream:
- `inbound` = audio Twilio receives from the party who originated/is connected on
  the parent call = the SELLER (the one who called the Twilio number).
- `outbound` = audio Twilio sends onward on that same call, which — once the
  `<Dial>` leg connects — carries the far end's voice = the PROSPECT (human,
  today; the same track would carry an AI agent's TTS output in a future
  speaker_mode, still resolved to a non-seller role by this same resolver).

Any OTHER call topology (inbound lead-response, a REST-API-originated outbound
call to the prospect with the seller bridged in separately, conference bridges
with more than two parties, warm transfers, ...) is explicitly OUT OF SCOPE for
this resolver and must not be assumed to work — see docs/DECISIONS.md ADR-043/053
for the full topology restriction and what would need to change to support
another one.

Clarified by ADR-058 (no logic change — the mapping below was already correct
for this case, only the parent leg's origin differs): placing the PARENT call
via Twilio's REST API instead of having the seller dial a purchased number in
is still IN SCOPE, as long as the REST call's `To` is the SELLER (not the
prospect) and the same `<Dial>` step still brings the prospect in as the child
leg — the Media Stream's `inbound`/`outbound` labels depend only on who is
connected on the parent leg and who is `<Dial>`-ed out afterward, never on
whether that parent leg was established by an inbound PSTN call or an
outbound-via-REST one. The explicitly out-of-scope case above remains: a REST
call placed directly `To` the prospect, with the seller bridged in separately
— that inverts which party is on the parent leg and would mislabel both roles
under this resolver's fixed mapping.

Extended by ADR-060 (no logic change) to a THIRD way of establishing the same
parent leg: the seller's own browser, via the Twilio Voice JS SDK
(`Device.connect()`), instead of a phone call (PSTN-inbound or REST-outbound-
to-self). Twilio's Media Streams track semantics do not distinguish a WebRTC
client leg from a PSTN one — `inbound` is still "audio Twilio receives from
whoever is connected on the parent leg" regardless of what kind of connection
that is, so a browser-originated parent leg with the seller on it, followed by
the same `<Dial>` step bringing the prospect in as the child leg, remains
structurally identical to the already-confirmed topology above and stays
`inbound` = seller / `outbound` = prospect under this same resolver. This has
been verified by re-reading Twilio's own Media Streams track documentation and
by re-confirming this resolver's code makes no assumption about the parent
leg's connection type anywhere — it has NOT yet been verified against an
actual live browser-originated call; that verification is the first real test
this topology is being prepared for, not something to assume in advance.
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
    outbound sales call flow AS ACTUALLY CONFIRMED for the first real test
    (see module docstring and ADR-053) — seller calls in (`inbound`), TwiML
    `<Dial>`s the prospect out (`outbound`), no additional parties on the bridge.

    `TOPOLOGY_NAME` was bumped to `_v2` when the inbound/outbound direction was
    corrected (ADR-053) — a v1-labelled row would have been recorded under the
    OPPOSITE mapping (there are none, since no real test call has happened yet).
    """
    TOPOLOGY_NAME = 'outbound_sales_flow_v2'

    def resolve(self, track: str) -> str:
        if track == INBOUND:
            return 'seller'
        if track == OUTBOUND:
            return 'prospect'
        return track  # unrecognized track name — surfaced as-is, never guessed


def get_default_speaker_role_resolver() -> SpeakerRoleResolver:
    """Seam entry point (mirrors app/secrets.get_secrets_provider() and
    app/streaming/asr.get_asr_provider()'s pattern): today always returns the one
    supported topology's resolver. A future call topology gets its own resolver
    class and a way to select it here — never a second hardcoded mapping scattered
    into TurnDetector or elsewhere."""
    return OutboundSalesFlowResolver()
