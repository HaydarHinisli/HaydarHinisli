"""Sprint 2: mu-law codec + VAD unit tests."""
import math

from app.streaming import mulaw
from app.streaming.vad import VoiceActivityDetector, rms


def test_mulaw_decode_silence_bytes_are_zero():
    assert mulaw.decode(bytes([0xFF]))[0] == 0
    assert mulaw.decode(bytes([0x7F]))[0] == 0


def test_mulaw_decode_matches_audioop_reference_for_all_256_bytes():
    import warnings
    warnings.filterwarnings('ignore')
    import audioop
    for b in range(256):
        mine = mulaw.decode(bytes([b]))[0]
        ref = int.from_bytes(audioop.ulaw2lin(bytes([b]), 2), 'little', signed=True)
        assert mine == ref, f'byte {b}: {mine} != {ref}'


def test_mulaw_round_trip_is_close_for_a_tone():
    samples = [int(9000 * math.sin(2 * math.pi * 200 * i / 8000)) for i in range(160)]
    encoded = mulaw.encode(samples)
    decoded = mulaw.decode(encoded)
    # mu-law is lossy (logarithmic quantization) — round trip should be close, not exact
    max_err = max(abs(a - b) for a, b in zip(samples, decoded))
    assert max_err < 500


def test_rms_of_silence_is_zero_and_of_tone_is_positive():
    assert rms([0, 0, 0]) == 0.0
    assert rms([100, -100, 100, -100]) > 0


def _tone_chunk(amplitude=9000, n=160, phase0=0):
    samples = [int(amplitude * math.sin(2 * math.pi * 200 * (phase0 + i) / 8000)) for i in range(n)]
    return mulaw.encode(samples)


def _silence_chunk(n=160):
    return bytes([mulaw.SILENCE_BYTE]) * n


def test_vad_detects_speech_and_returns_to_silence_after_hangover():
    vad = VoiceActivityDetector()
    speaking, _ = vad.process_chunk(_silence_chunk())
    assert speaking is False

    speaking, energy = vad.process_chunk(_tone_chunk())
    assert speaking is True
    assert energy > vad.energy_threshold

    # hangover_ms=300, chunk_ms=20 -> 15 silent chunks needed to fall silent again
    for _ in range(14):
        speaking, _ = vad.process_chunk(_silence_chunk())
        assert speaking is True  # still within hangover window
    speaking, _ = vad.process_chunk(_silence_chunk())
    assert speaking is False


def test_vad_brief_pause_within_hangover_does_not_end_speech():
    vad = VoiceActivityDetector()
    vad.process_chunk(_tone_chunk())
    for _ in range(5):  # 100ms of silence, well under the 300ms hangover
        speaking, _ = vad.process_chunk(_silence_chunk())
        assert speaking is True
    speaking, _ = vad.process_chunk(_tone_chunk())
    assert speaking is True
