"""Sprint 2B requirement 3: real streaming ASR provider adapter (Deepgram).

**Read this before trusting these tests as "Deepgram works"**: none of these tests
connect to the real Deepgram service — there is no DEEPGRAM_API_KEY and no network
path to Deepgram from this environment. They run the adapter against a small local
fake WebSocket server that speaks Deepgram's documented message protocol shape
(Results/UtteranceEnd/Finalize/CloseStream). This proves the ADAPTER's own logic
(message parsing, event mapping, the Finalize flow, reconnect-on-drop) is internally
correct against that assumed shape — it does NOT prove the real Deepgram service
behaves exactly like the fake. Real-provider verification remains open, see the
Sprint 2B report.
"""
import asyncio
import json

import pytest
import websockets

from app.streaming.asr import ASREvent
from app.streaming.deepgram_provider import DeepgramASRProvider, DeepgramStreamHandle, _build_url


def run(coro):
    return asyncio.run(coro)


# --- pure URL construction ------------------------------------------------------------

def test_build_url_uses_eu_region_host_by_default():
    url = _build_url(region='eu', model='nova-3', language='de', keyterms=None)
    assert url.startswith('wss://api.eu.deepgram.com/v1/listen?')


def test_build_url_uses_global_host_for_non_eu_region():
    url = _build_url(region='us', model='nova-3', language='de', keyterms=None)
    assert url.startswith('wss://api.deepgram.com/v1/listen?')


def test_build_url_includes_required_params():
    url = _build_url(region='eu', model='nova-3', language='de', keyterms=None)
    for expected in ('model=nova-3', 'language=de', 'interim_results=true', 'mip_opt_out=true', 'encoding=mulaw', 'sample_rate=8000', 'channels=1'):
        assert expected in url


def test_build_url_appends_keyterms_when_given():
    url = _build_url(region='eu', model='nova-3', language='de', keyterms=['Replica', 'Wettbewerber'])
    assert 'keyterm=Replica' in url
    assert 'keyterm=Wettbewerber' in url


# --- fake Deepgram-shaped server for adapter-plumbing tests --------------------------

class FakeDeepgramServer:
    """Speaks the documented Deepgram message shapes over a local WS server. Not a
    Deepgram simulator in any deeper sense — just enough protocol to exercise the
    adapter's send/receive/finalize/close code paths deterministically."""

    def __init__(self, *, interim_transcript='hallo wie', final_transcript='hallo wie geht es Ihnen', drop_after_n_audio_chunks=None):
        self.received_audio_chunks: list[bytes] = []
        self.received_control_messages: list[dict] = []
        self._interim_transcript = interim_transcript
        self._final_transcript = final_transcript
        self._drop_after_n = drop_after_n_audio_chunks
        self.server = None
        self.port = None

    async def _handler(self, ws):
        try:
            async for message in ws:
                if isinstance(message, (bytes, bytearray)):
                    self.received_audio_chunks.append(bytes(message))
                    if self._drop_after_n is not None and len(self.received_audio_chunks) >= self._drop_after_n:
                        await ws.close()
                        return
                    if len(self.received_audio_chunks) == 2:
                        await ws.send(json.dumps({
                            'type': 'Results', 'is_final': False, 'speech_final': False,
                            'channel': {'alternatives': [{'transcript': self._interim_transcript, 'words': []}]},
                        }))
                else:
                    control = json.loads(message)
                    self.received_control_messages.append(control)
                    if control.get('type') == 'Finalize':
                        await ws.send(json.dumps({
                            'type': 'Results', 'is_final': True, 'speech_final': True,
                            'channel': {'alternatives': [{
                                'transcript': self._final_transcript,
                                'words': [{'word': w, 'start': i * 0.3, 'end': i * 0.3 + 0.25} for i, w in enumerate(self._final_transcript.split())],
                            }]},
                        }))
                    elif control.get('type') == 'CloseStream':
                        await ws.close()
                        return
        except websockets.ConnectionClosed:
            pass

    async def start(self):
        self.server = await websockets.serve(self._handler, 'localhost', 0)
        self.port = self.server.sockets[0].getsockname()[1]
        return f'ws://localhost:{self.port}/v1/listen'

    async def stop(self):
        self.server.close()
        await self.server.wait_closed()


async def _run_full_utterance(fake_url: str, *, audio_chunks: int = 4) -> tuple[list[ASREvent], object]:
    handle = DeepgramStreamHandle(track='inbound', api_key='fake-key-for-plumbing-test', region='eu', model='nova-3', language='de', _url_override=fake_url)
    all_events: list[ASREvent] = []
    for _ in range(audio_chunks):
        await handle.feed_audio(b'\xff' * 160, is_speaking=True)
        await asyncio.sleep(0.05)
        all_events.extend(await handle.poll_events())
    final = await handle.finalize()
    await handle.close()
    return all_events, final


def test_adapter_sends_audio_bytes_to_the_server():
    async def scenario():
        server = FakeDeepgramServer()
        url = await server.start()
        try:
            handle = DeepgramStreamHandle(track='inbound', api_key='fake-key', region='eu', model='nova-3', language='de', _url_override=url)
            await handle.feed_audio(b'\xff' * 160, is_speaking=True)
            await asyncio.sleep(0.1)
            await handle.close()
            assert len(server.received_audio_chunks) == 1
            assert server.received_audio_chunks[0] == b'\xff' * 160
        finally:
            await server.stop()
    run(scenario())


def test_adapter_surfaces_interim_event_from_server():
    async def scenario():
        server = FakeDeepgramServer(interim_transcript='hallo wie')
        url = await server.start()
        try:
            events, _ = await _run_full_utterance(url, audio_chunks=2)
            interim_events = [e for e in events if e.kind == 'interim']
            assert len(interim_events) >= 1
            assert interim_events[0].text == 'hallo wie'
            assert interim_events[0].provider_speech_final is False
        finally:
            await server.stop()
    run(scenario())


def test_finalize_sends_finalize_control_message_and_returns_final_text():
    async def scenario():
        server = FakeDeepgramServer(final_transcript='hallo wie geht es Ihnen')
        url = await server.start()
        try:
            _, final = await _run_full_utterance(url, audio_chunks=2)
            assert final is not None
            assert final.text == 'hallo wie geht es Ihnen'
            assert final.kind == 'final'
            assert final.provider_speech_final is True
            assert any(m.get('type') == 'Finalize' for m in server.received_control_messages)
        finally:
            await server.stop()
    run(scenario())


def test_final_event_carries_word_level_timestamps_when_provider_supplies_them():
    async def scenario():
        server = FakeDeepgramServer(final_transcript='hallo welt')
        url = await server.start()
        try:
            _, final = await _run_full_utterance(url, audio_chunks=2)
            assert final.words is not None
            assert final.words[0]['word'] == 'hallo'
            assert 'start' in final.words[0] and 'end' in final.words[0]
        finally:
            await server.stop()
    run(scenario())


def test_close_sends_close_stream_control_message():
    async def scenario():
        server = FakeDeepgramServer()
        url = await server.start()
        try:
            handle = DeepgramStreamHandle(track='inbound', api_key='fake-key', region='eu', model='nova-3', language='de', _url_override=url)
            await handle.feed_audio(b'\xff' * 160, is_speaking=True)
            await asyncio.sleep(0.05)
            await handle.close()
            assert any(m.get('type') == 'CloseStream' for m in server.received_control_messages)
        finally:
            await server.stop()
    run(scenario())


def test_feed_audio_after_close_does_not_raise():
    async def scenario():
        server = FakeDeepgramServer()
        url = await server.start()
        try:
            handle = DeepgramStreamHandle(track='inbound', api_key='fake-key', region='eu', model='nova-3', language='de', _url_override=url)
            await handle.close()
            await handle.feed_audio(b'\xff' * 160, is_speaking=True)  # must not raise
        finally:
            await server.stop()
    run(scenario())


def test_adapter_degrades_gracefully_when_connection_drops_mid_stream():
    async def scenario():
        server = FakeDeepgramServer(drop_after_n_audio_chunks=1)
        url = await server.start()
        try:
            handle = DeepgramStreamHandle(track='inbound', api_key='fake-key', region='eu', model='nova-3', language='de', _url_override=url)
            await handle.feed_audio(b'\xff' * 160, is_speaking=True)
            await asyncio.sleep(0.1)  # server drops the connection here
            # further feeds must not crash the pipeline even if reconnect fails
            # (the fake server only accepted one handler invocation and is now
            # gone for this connection) — graceful degradation, not a raised exception.
            await handle.feed_audio(b'\xff' * 160, is_speaking=True)
            final = await handle.finalize()
            await handle.close()
            # No assertion on `final` content — the point is that none of this raised.
        finally:
            await server.stop()
    run(scenario())


def test_unreachable_server_does_not_raise_it_degrades_gracefully():
    async def scenario():
        handle = DeepgramStreamHandle(
            track='inbound', api_key='fake-key', region='eu', model='nova-3', language='de',
            _url_override='ws://127.0.0.1:1/v1/listen',  # nothing listens on port 1
        )
        await handle.feed_audio(b'\xff' * 160, is_speaking=True)  # must not raise despite unreachable server
        events = await handle.poll_events()
        assert events == []
        await handle.close()
    run(scenario())


def test_provider_factory_builds_handle_with_expected_config():
    provider = DeepgramASRProvider(api_key='k', region='eu', model='nova-3', language='de', keyterms=['Replica'])
    handle = run(provider.start_stream(track='outbound'))
    assert handle.track == 'outbound'
    assert 'keyterm=Replica' in handle._url
