# Deployment / Operations Notes

This is not a full ops runbook — it exists to hold the deployment-topology
constraints that are easy to violate silently if they only lived in code comments.

## Live Suggestion Push: single-instance / sticky-bound topology required (pilot)

`app/services/live_push.LiveSuggestionHub` (Sprint 3A, `docs/DECISIONS.md`
ADR-048) is an **in-process, in-memory** WebSocket registry. It is accepted for
the pilot as-is — **no Redis/NATS/other pub-sub backplane has been built**, and
none should be added speculatively before it's actually needed.

What this means operationally: a seller's browser connects to
`/ws/live/{call_id}` on ONE specific application process. `LiveSuggestionHub`
only knows about connections registered on that same process. If the persisted
Suggestion for that seller's call is produced by a **different** process (e.g. a
second uvicorn/gunicorn worker, or a second container/instance behind a
load balancer), that browser will never receive the push — it silently sees
nothing, with no error, until the next `sync` on reconnect at best.

Concretely, the pilot deployment MUST be one of:
- **A single application process/instance** (simplest, recommended for the pilot).
- **Multiple processes, but with session affinity ("sticky sessions")** at the
  load balancer, keyed so that a given `call_id`'s Media Streams WebSocket
  connection (`/ws/twilio-media`, which produces the Suggestion) and that same
  call's `/ws/live/{call_id}` connection (which receives it) are always routed to
  the SAME process. Sticky-by-call_id is not a standard load-balancer feature
  (most only offer client-IP or cookie-based stickiness), so in practice this
  reduces to running a single process for the pilot unless a specific LB
  configuration achieving this has been verified.

**Do not** deploy multiple independent, non-sticky application instances behind
a load balancer while this limitation stands — Live Suggestion Push will
silently fail for any call whose two WebSocket connections land on different
instances. If/when multi-instance deployment becomes a real requirement, the fix
is a shared pub/sub layer (Redis Streams/Pub-Sub, NATS, or similar) in front of
the same `register()`/`publish_suggestion()` interface `LiveSuggestionHub`
already exposes — not a redesign of the calling code in
`app/streaming/pipeline.py` or `app/main.py`.

This same single-instance assumption is also relied on by
`TurnLatencyTrace.t_turn_end_detected_monotonic` (`docs/DECISIONS.md` ADR-051):
comparing a `time.monotonic()` reading from turn-end against one read later, when
the Render-ACK HTTP request arrives, is only valid if both reads happen on the
same machine's uptime clock without a restart in between — true under this same
single-instance/sticky topology, not guaranteed otherwise.
