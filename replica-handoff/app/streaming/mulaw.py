"""G.711 mu-law codec (Sprint 2): Twilio Media Streams send audio as 8kHz mono
G.711 mu-law by default (see docs/PROVIDER_REFERENCES.md). REPLICA needs to decode
this to compute real signal energy for voice-activity detection (app/streaming/vad.py).

Deliberately NOT using the stdlib `audioop` module: it is deprecated and slated for
removal (Python 3.13, see PEP 594) — a stdlib dependency this codebase would have to
rip out again soon. This is a small, self-contained implementation of the standard
ITU-T G.711 mu-law algorithm instead (the same algorithm `audioop.ulaw2lin`/
`lin2ulaw` implement), verified against the well-known reference points (0xFF/0x7F
decode to silence; see tests/test_streaming_mulaw.py).
"""
from __future__ import annotations
import bisect

_BIAS = 0x84  # 132, the standard mu-law encoding bias


def _decode_byte(u_val: int) -> int:
    """Standard mu-law -> 16-bit linear PCM decode for a single byte."""
    u_val = ~u_val & 0xFF
    t = ((u_val & 0x0F) << 3) + _BIAS
    t <<= (u_val & 0x70) >> 4
    return _BIAS - t if (u_val & 0x80) else t - _BIAS


_DECODE_TABLE: tuple[int, ...] = tuple(_decode_byte(b) for b in range(256))

# Sorted (sample_value, byte) pairs for encode-by-nearest-neighbour, built once.
_ENCODE_LOOKUP: list[tuple[int, int]] = sorted((v, b) for b, v in enumerate(_DECODE_TABLE))
_ENCODE_VALUES: list[int] = [v for v, _ in _ENCODE_LOOKUP]


def decode(data: bytes) -> list[int]:
    """Mu-law encoded bytes -> list of 16-bit signed linear PCM samples."""
    table = _DECODE_TABLE
    return [table[b] for b in data]


def encode_sample(sample: int) -> int:
    """Nearest-neighbour linear PCM sample -> mu-law byte. Not bit-exact to any
    particular hardware encoder (not required — only used to synthesize test/demo
    audio); decode() above is the one that has to be standards-correct, since real
    Twilio audio only ever needs to be decoded, never re-encoded by REPLICA."""
    sample = max(-32768, min(32767, sample))
    idx = bisect.bisect_left(_ENCODE_VALUES, sample)
    if idx == 0:
        return _ENCODE_LOOKUP[0][1]
    if idx == len(_ENCODE_VALUES):
        return _ENCODE_LOOKUP[-1][1]
    before = _ENCODE_LOOKUP[idx - 1]
    after = _ENCODE_LOOKUP[idx]
    closer = before if (sample - before[0]) <= (after[0] - sample) else after
    return closer[1]


def encode(samples: list[int]) -> bytes:
    return bytes(encode_sample(s) for s in samples)


SILENCE_BYTE = 0xFF  # decodes to 0 — the conventional mu-law silence byte
