"""Seller Frontend v1 (docs/DECISIONS.md, Seller-Frontend sprint): structural
regression test for app/static/live.html.

This project has no JS test tooling, so the "UI-relevant states" the operator
asked to have covered are verified the same way the rest of this codebase
verifies behavior: by reading the served markup/script as text and asserting
the invariants that matter, rather than by adding a new frontend test stack
for one file. What is guarded here:

- The three connection states v1 actually implements (each backed by a real
  WS lifecycle event) are present, and no *invented* conversation state
  ("Prospect spricht", "REPLICA analysiert" or similar) has crept back in.
- The neutral empty-state placeholder text is exactly the wording specified.
- Debug-only fields (trace_id, ASR provider, synthetic flag, latencies,
  call_id, turn_id) render only inside the closed-by-default <details> debug
  disclosure, never in the normal seller view.
"""
import re
from pathlib import Path

LIVE_HTML = Path(__file__).resolve().parent.parent / 'app' / 'static' / 'live.html'


def _read() -> str:
    return LIVE_HTML.read_text(encoding='utf-8')


def _debug_block(html: str) -> str:
    start = html.index('<details class="debug-toggle"')
    end = html.index('</details>', start)
    return html[start:end]


def _strip_js_line_comments(html: str) -> str:
    return '\n'.join(
        line for line in html.splitlines() if not line.strip().startswith('//')
    )


def _handle_suggestion_body(html: str) -> str:
    start = html.index('function handleSuggestion')
    end = html.index('function renderDebug', start)
    return html[start:end]


def test_three_approved_connection_states_are_present():
    html = _read()
    assert "'Bereit'" in html
    assert "'Verbindung unterbrochen — Wiederverbindung läuft …'" in html
    assert "'Getrennt'" in html


def test_no_invented_conversation_states_present():
    # Comments are allowed to explain *why* these states were deliberately
    # left out (see the setConnectionState() docstring-comment) — only actual
    # user-visible strings would be a regression.
    html = _strip_js_line_comments(_read())
    for forbidden in ('Prospect spricht', 'REPLICA analysiert', 'Analyse läuft', 'Gespräch läuft'):
        assert forbidden not in html, f'invented state string leaked into live.html: {forbidden!r}'


def test_empty_state_placeholder_is_exact_neutral_wording():
    html = _read()
    assert 'Bereit für den nächsten Hinweis' in html
    assert "var SAG_PLACEHOLDER = 'Bereit für den nächsten Hinweis';" in html
    # No leftover Sprint 3A testharness placeholder wording.
    assert 'Noch keine Suggestion empfangen' not in html


def test_debug_disclosure_is_closed_by_default_and_placed_last():
    html = _read()
    details_tag_start = html.index('<details class="debug-toggle"')
    details_tag_end = html.index('>', details_tag_start)
    opening_tag = html[details_tag_start:details_tag_end + 1]
    assert 'open' not in opening_tag, 'debug view must be collapsed by default'
    # It must come after the main copilot area and the history section.
    assert html.index('class="copilot"') < details_tag_start
    assert html.index('id="historySection"') < details_tag_start


def test_debug_only_fields_are_confined_to_the_debug_block():
    html = _read()
    debug_block = _debug_block(html)
    debug_only_markers = ["'trace_id'", "'ASR Provider'", "'Synthetisch?'", "'turn_id'", 'd.latencies_ms']
    for marker in debug_only_markers:
        assert marker in html, f'expected debug marker missing entirely: {marker!r}'
        # The markers legitimately exist once, inside renderDebug() (which
        # mounts them into #debugPanel, itself inside the <details> block).
        assert marker in debug_block or marker in html[html.index('function renderDebug'):]

    # The function that updates the *normal* seller view (handleSuggestion,
    # everything before renderDebug is invoked) must never reference them.
    main_view_body = _handle_suggestion_body(html)
    for marker in debug_only_markers:
        assert marker not in main_view_body, (
            f'debug-only marker {marker!r} leaked into the main seller view update path'
        )


def test_normal_seller_view_has_no_testharness_framing():
    html = _read()
    assert '<h1>' not in html
    assert 'Testharness' not in html


def test_connect_card_hides_call_id_and_token_once_connected():
    html = _read()
    assert "els.connectCard.hidden = true" in html
    assert "els.connectCard.hidden = false" in html


def test_new_suggestion_uses_subtle_flash_not_animation_or_layout_shift():
    html = _read()
    assert "els.sag.classList.add('flash')" in html
    # Guard against reintroducing a jumpy/animated highlight (movement or
    # resizing) — a color/box-shadow-only flash is fine, so we only forbid
    # the actual layout-shifting techniques, not unrelated text-transform CSS.
    assert '@keyframes' not in html
    assert not re.search(r'(?<!-)transform\s*:', html)
    assert 'scale(' not in html
    assert 'translate' not in html


def test_exactly_one_previous_suggestion_kept_as_history():
    html = _read()
    assert 'id="historyText"' in html
    assert 'previousSuggestionText = els.sag.textContent;' in html
    # Only one history slot exists — no array/list of past suggestions.
    assert 'historyList' not in html
    assert 'suggestionHistory' not in html


# --- Token normalization + no-endless-reconnect-on-auth-failure (ADR-057) ------------


def test_token_is_sanitized_before_being_sent_to_the_server():
    html = _read()
    assert 'function sanitizeToken(' in html
    assert 'var token = sanitizeToken(els.token.value);' in html
    # Must strip an accidentally-pasted "Bearer " scheme prefix, case-insensitively.
    assert re.search(r"/\^bearer\\s\+/i", html)


def test_policy_close_does_not_trigger_an_endless_reconnect_loop():
    html = _read()
    # The close handler must read the CloseEvent's code and treat 1008
    # (server policy rejection: bad/expired token, disallowed origin, wrong
    # tenant) as terminal for the current credentials, not just another
    # transient drop to blindly retry forever with the same rejected token.
    assert "ws.addEventListener('close', function (event)" in html
    assert "event.code === 1008" in html
    close_handler_start = html.index("ws.addEventListener('close'")
    close_handler_end = html.index('});', close_handler_start)
    close_handler_body = html[close_handler_start:close_handler_end]
    assert "setConnectionState('auth-error')" in close_handler_body
    # The auth-error branch must return before reaching scheduleReconnect().
    auth_error_idx = close_handler_body.index("setConnectionState('auth-error')")
    schedule_idx = close_handler_body.index('scheduleReconnect()')
    assert auth_error_idx < schedule_idx


def test_auth_error_state_shows_a_clear_actionable_message():
    html = _read()
    assert "state === 'auth-error'" in html
    assert 'Authentifizierung fehlgeschlagen' in html


def test_ready_state_is_only_set_from_a_real_server_ack_not_on_raw_ws_open():
    """Regression guard (ADR-058, found by the real-browser E2E test): the
    'open' handler fires as soon as the socket connects, before the server
    has validated the auth frame at all — setting 'ready' there would flash
    the authenticated state even for a token the server is about to reject.
    'ready' must only be set once the server's own auth_ok/sync message
    proves the auth frame was actually accepted."""
    html = _read()
    open_handler_start = html.index("ws.addEventListener('open'")
    open_handler_end = html.index('});', open_handler_start)
    open_handler_body = html[open_handler_start:open_handler_end]
    assert "setConnectionState('ready')" not in open_handler_body

    message_handler_start = html.index("ws.addEventListener('message'")
    message_handler_end = html.index('});', message_handler_start)
    message_handler_body = html[message_handler_start:message_handler_end]
    assert "msg.type === 'auth_ok'" in message_handler_body
    assert "setConnectionState('ready')" in message_handler_body


# --- ADR-060: real browser-originated test call (Twilio Voice JS SDK) ---------------


def test_voice_sdk_is_loaded_from_a_vendored_local_file_not_a_third_party_cdn():
    """Twilio's Voice JS SDK v2+ is no longer CDN-hosted (confirmed against the
    SDK's own README before vendoring it) — it must be self-hosted. Guards
    against a future edit reverting to a third-party <script src> that may not
    exist or may serve an unpinned/untrusted version."""
    html = _read()
    assert '<script src="/static/vendor/twilio-voice-sdk.min.js"></script>' in html
    for forbidden_host in ('cdn.jsdelivr.net', 'unpkg.com', 'sdk.twilio.com'):
        assert forbidden_host not in html


def test_vendored_voice_sdk_file_exists_and_is_valid_js():
    vendor_path = LIVE_HTML.parent / 'vendor' / 'twilio-voice-sdk.min.js'
    assert vendor_path.is_file(), 'vendored Twilio Voice SDK file is missing'
    content = vendor_path.read_text(encoding='utf-8')
    assert len(content) > 10_000  # a real bundle, not an empty/error placeholder
    assert 'Device' in content


def test_prospect_number_field_is_never_prefilled_or_persisted():
    html = _read()
    assert 'id="prospectNumber"' in html
    input_tag_start = html.index('id="prospectNumber"')
    input_tag_end = html.index('/>', input_tag_start)
    input_tag = html[input_tag_start:input_tag_end]
    assert 'value=' not in input_tag  # never prefilled with anything, let alone a real number
    assert 'autocomplete="off"' in input_tag
    # No real-looking phone number literal anywhere in the file (placeholder
    # text like "+49…" is fine; a specific dialable-looking number is not).
    assert not re.search(r'\+49\d{6,}', html)


def test_prospect_number_is_cleared_immediately_after_reading_and_never_logged():
    html = _read()
    click_handler_start = html.index("els.voiceCallBtn.addEventListener('click'")
    click_handler_end = html.index('\n  });', click_handler_start)
    handler_body = html[click_handler_start:click_handler_end]
    read_idx = handler_body.index('els.prospectNumber.value.trim()')
    clear_idx = handler_body.index("els.prospectNumber.value = ''")
    assert read_idx < clear_idx, 'prospect number must be cleared from the field right after reading it'
    for forbidden in ('console.log', 'console.info', 'console.warn', 'console.debug'):
        assert forbidden not in handler_body


def test_voice_call_validates_e164_before_connecting():
    html = _read()
    assert 'var E164_RE = /^\\+[1-9]\\d{6,14}$/;' in html
    assert 'E164_RE.test(prospectNumber)' in html


def test_device_connect_sends_replica_call_id_as_custom_parameter():
    html = _read()
    assert "params: { To: prospectNumber, replica_call_id: String(currentCallId) }" in html


def test_voice_test_ui_lives_inside_the_debug_view_not_the_main_seller_view():
    """ADR-056 reclassified /live/{call_id} as the technical debug view — this
    real-call test tool belongs there, not in the calm main copilot area."""
    html = _read()
    debug_details_start = html.index('<details class="debug-toggle"')
    debug_details_end = html.index('</details>', debug_details_start)
    debug_block = html[debug_details_start:debug_details_end]
    assert 'id="voiceTest"' in debug_block
    assert 'id="voiceTest"' not in html[:debug_details_start]


def test_device_edge_comes_from_the_server_response_not_hardcoded():
    """ADR-061: the Voice SDK's own default edge is 'roaming' (nearest-latency
    auto-selection), not necessarily the EU edge (TWILIO_EDGE) this account is
    pinned to everywhere else — must be passed explicitly, sourced from the
    /api/voice/access-token response rather than a second hardcoded copy."""
    html = _read()
    assert 'new Twilio.Device(body.token, { edge: body.edge })' in html
    # Regression guard: no hardcoded edge string literal anywhere (e.g. a
    # stray "edge: 'dublin'" that would silently drift from TWILIO_EDGE).
    assert not re.search(r"edge:\s*'[a-z-]+'", html)
