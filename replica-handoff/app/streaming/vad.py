"""Minimal energy-based voice-activity detection over decoded mu-law audio
(Sprint 2). This is real signal processing on real signal energy — RMS over
actually-decoded PCM samples — not a placeholder; what IS necessarily a stand-in
(documented in app/streaming/asr.py) is the ASR transcript *content*, since no live
ASR vendor is reachable from this environment. Turn-end detection built on this VAD
does not depend on that stand-in at all.

Deliberately simple: a fixed RMS energy threshold plus a hangover window (how long
silence must persist before a track is considered to have stopped talking), matching
docs/ARCHITECTURE.md's "Audio Features" box conceptually while staying easy to reason
about and unit-test. A production pilot would likely want an adaptive noise floor;
that is out of scope for proving the pipeline shape in this sprint (see final report
tech-debt section) — the seam (`VoiceActivityDetector.energy_threshold`) exists for
exactly that later refinement.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .mulaw import decode


def rms(samples: list[int]) -> float:
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5


@dataclass
class VoiceActivityDetector:
    """Tracks one audio track's speaking/silent state across successive chunks.
    `chunk_ms` is how much audio one call to `process_chunk()` represents (Twilio's
    default media frame is 20ms); `hangover_ms` is how long RMS must stay below
    threshold before the track is declared silent again — this absorbs brief natural
    pauses within a single utterance (a breath, a stressed syllable gap) so they
    aren't misread as the utterance ending.
    """
    energy_threshold: float = 400.0
    chunk_ms: float = 20.0
    hangover_ms: float = 300.0

    is_speaking: bool = False
    _silence_ms_accum: float = field(default=0.0, repr=False)

    def process_chunk(self, payload: bytes) -> tuple[bool, float]:
        """Feeds one mu-law-encoded chunk. Returns (is_speaking_now, energy)."""
        energy = rms(decode(payload))
        loud = energy >= self.energy_threshold
        if loud:
            self._silence_ms_accum = 0.0
            self.is_speaking = True
        else:
            self._silence_ms_accum += self.chunk_ms
            if self._silence_ms_accum >= self.hangover_ms:
                self.is_speaking = False
        return self.is_speaking, energy
