from __future__ import annotations
import base64
from dataclasses import dataclass, field


@dataclass
class TwilioStreamState:
    stream_sid: str | None = None
    call_sid: str | None = None
    chunks: int = 0
    tracks: dict[str, int] = field(default_factory=dict)
    bytes_received: int = 0

    def consume(self, message: dict) -> None:
        event = message.get('event')
        if event == 'start':
            start = message.get('start', {})
            self.stream_sid = start.get('streamSid')
            self.call_sid = start.get('callSid')
        elif event == 'media':
            media = message.get('media', {})
            track = media.get('track', 'unknown')
            self.tracks[track] = self.tracks.get(track, 0) + 1
            self.chunks += 1
            payload = media.get('payload', '')
            if payload:
                try:
                    self.bytes_received += len(base64.b64decode(payload))
                except Exception:
                    pass
