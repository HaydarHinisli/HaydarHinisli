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
    """ADR-063: the guarded-start function (startVoiceTestCall) is now the ONLY
    path that can ever place a real call — its double-start guard is deliberately
    the very first statement, ahead of even reading the prospect number, but the
    number must still be cleared from the field before any further check/await."""
    html = _read()
    handler_start = html.index('async function startVoiceTestCall()')
    handler_end = html.index('\n  }\n\n  els.voiceCallBtn.addEventListener', handler_start)
    handler_body = html[handler_start:handler_end]
    guard_idx = handler_body.index("callState !== 'ready'")
    read_idx = handler_body.index('els.prospectNumber.value.trim()')
    clear_idx = handler_body.index("els.prospectNumber.value = ''")
    assert guard_idx < read_idx, 'the double-start guard must run before the prospect number is ever read'
    assert read_idx < clear_idx, 'prospect number must be cleared from the field right after reading it'
    for forbidden in ('console.log', 'console.info', 'console.warn', 'console.debug'):
        assert forbidden not in handler_body


def test_voice_call_validates_e164_before_connecting():
    html = _read()
    assert 'var E164_RE = /^\\+[1-9]\\d{6,14}$/;' in html
    assert 'E164_RE.test(prospectNumber)' in html


def test_device_connect_sends_replica_voice_ticket_never_a_raw_call_id():
    """ADR-063 (item 7/8): a raw call_id must never travel from the browser to
    the voice-outbound webhook — only the short-lived, server-verified ticket
    minted by /api/voice/access-token, which the webhook alone decodes to learn
    the real (tenant-checked) call_id. See tests/test_voice_outbound.py for the
    server-side enforcement this frontend contract depends on."""
    html = _read()
    assert 'params: { To: prospectNumber, replica_voice_ticket: tokenBody.voice_ticket }' in html
    assert 'replica_call_id: String(currentCallId)' not in html


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
    assert 'new Twilio.Device(tokenBody.token, { edge: tokenBody.edge })' in html
    # Regression guard: no hardcoded edge string literal anywhere (e.g. a
    # stray "edge: 'dublin'" that would silently drift from TWILIO_EDGE).
    assert not re.search(r"edge:\s*'[a-z-]+'", html)


# --- ADR-063 (red-team hardening) --------------------------------------------------

def _start_voice_test_call_body(html: str) -> str:
    start = html.index('async function startVoiceTestCall()')
    end = html.index('\n  }\n\n  els.voiceCallBtn.addEventListener', start)
    return html[start:end]


def test_item1_double_start_guard_is_the_very_first_statement():
    """The double-start/double-call guard must run before ANYTHING else in the
    one function that can ever place a real call — including before the
    prospect number is read, before the preflight check, before any await —
    so neither a second click nor Enter-while-a-call-is-in-flight can ever
    reach past it, no matter how fast."""
    html = _read()
    body = _start_voice_test_call_body(html)
    first_line = body.strip().splitlines()[0]
    assert first_line == 'async function startVoiceTestCall() {'
    second_line = body.strip().splitlines()[1].strip()
    guard = "if (callState !== 'ready' && callState !== 'ended' && callState !== 'failed') return;"
    assert second_line == guard, 'the double-start guard must be the first statement in startVoiceTestCall()'


def test_item1_click_and_enter_key_both_invoke_the_same_single_start_function():
    """No second, parallel "start a call" code path may exist — both the
    button's click and Enter-in-the-number-field must route through the exact
    same guarded function, so they can never drift out of sync with each
    other (e.g. one gaining a new check the other doesn't)."""
    html = _read()
    assert "els.voiceCallBtn.addEventListener('click', startVoiceTestCall);" in html
    keydown_start = html.index("els.prospectNumber.addEventListener('keydown'")
    keydown_end = html.index('});', keydown_start)
    keydown_body = html[keydown_start:keydown_end]
    assert 'startVoiceTestCall();' in keydown_body
    # Regression guard: no second inline call-starting implementation.
    assert html.count('async function startVoiceTestCall()') == 1


def test_item1_call_button_is_disabled_for_the_whole_in_flight_duration():
    """Belt-and-suspenders alongside the guard above: the button itself must
    stay disabled (so a disabled button never even dispatches a click event)
    for exactly connecting/ringing/connected/ending, and re-enabled only for
    ready/ended/failed."""
    html = _read()
    render_start = html.index('function renderVoiceStatus()')
    render_end = html.index('\n  }\n\n  function setVoiceStatusText', render_start)
    body = html[render_start:render_end]
    assert "callState === 'ready' || callState === 'ended' || callState === 'failed'" in body
    assert 'els.voiceCallBtn.disabled = !canStartNewCall;' in body


def test_item2_call_state_is_only_ever_assigned_inside_its_one_setter():
    """docs/DECISIONS.md ADR-063 item 2: the call state must come from the
    real Twilio Device/Call SDK events, never be assumed/optimistically set —
    enforced structurally here by requiring `callState = ` to appear exactly
    once in the whole file, inside setCallState() itself; every other update
    must go through that one function."""
    html = _read()
    # Excludes the one-time `var callState = 'ready';` initial declaration —
    # every TRANSITION after that must go through setCallState().
    assignment_lines = [
        line for line in html.splitlines()
        if re.search(r'(?<!\w)callState = ', line) and 'var callState' not in line
    ]
    assert len(assignment_lines) == 1, f'callState must be assigned in exactly one place (setCallState), found: {assignment_lines}'
    setter_start = html.index('function setCallState(state, opts)')
    setter_end = html.index('\n  }\n\n  function setAnalysisState', setter_start)
    assert 'callState = state;' in html[setter_start:setter_end]


def test_item2_every_real_call_state_transition_comes_from_a_twilio_sdk_event():
    """Each of the seven required call states (Ready/Connecting/Ringing/
    Connected/Ending/Ended/Failed) must be reachable, and the four terminal/
    live ones (ringing/connected/ended/failed) only via a real call.on(...)
    handler — never a bare timeout or a guess."""
    html = _read()
    for state in ('ready', 'connecting', 'ringing', 'connected', 'ending', 'ended', 'failed'):
        assert f"{state}:" in html, f'missing call-state label for {state!r}'
    body = _start_voice_test_call_body(html)
    assert "call.on('ringing', function () { setCallState('ringing'); });" in body
    assert "call.on('accept', function () { setCallState('connected'); });" in body
    assert "call.on('disconnect', function () { onCallEnded('ended'); });" in body
    assert "call.on('cancel', function () { onCallEnded('ended'); });" in body
    assert "call.on('reject', function () { onCallEnded('ended'); });" in body
    assert "onCallEnded('failed'" in body


def test_item3_analysis_state_is_independent_of_call_state_and_combined_only_when_connected():
    """docs/DECISIONS.md ADR-063 item 3: a connected phone call must never be
    displayed as if it proves REPLICA's own analysis pipeline is working —
    the analysis label is only ever shown ALONGSIDE (never instead of) "Call
    verbunden", and analysisState is driven exclusively by server
    pipeline_status pushes, never inferred from callState anywhere."""
    html = _read()
    assert "} else if (msg.type === 'pipeline_status') {" in html
    assert 'setAnalysisState(msg.status, msg.detail);' in html
    render_start = html.index('function renderVoiceStatus()')
    render_end = html.index('\n  }\n\n  function setVoiceStatusText', render_start)
    body = html[render_start:render_end]
    assert "callState === 'connected' || callState === 'ending'" in body
    assert "'Call verbunden – ' + analysisLabel()" in body
    # setAnalysisState() is reset to 'waiting' once, at the very start of a new
    # call attempt (a fresh baseline for THIS call, not call-state driving
    # analysis progress) — but no call.on(...) event handler may call it with
    # anything else; only real pipeline_status pushes may report progress.
    call_handler_body = _start_voice_test_call_body(html)
    assert call_handler_body.count('setAnalysisState') == 1
    assert "setAnalysisState('waiting');" in call_handler_body


def test_item3_disrupted_detail_labels_match_the_users_own_two_examples():
    """The user's own two example messages ("Call verbunden – Analyse nicht
    verfügbar" / "Call verbunden – Deepgram nicht verfügbar") must both be
    reachable exactly as worded."""
    html = _read()
    assert "disrupted: 'Analyse nicht verfügbar'," in html
    assert "deepgram_unavailable: 'Deepgram nicht verfügbar'," in html


def test_item4_a_new_suggestion_clears_staleness_but_stale_push_overrides_reconnect_sync():
    html = _read()
    assert "} else if (msg.type === 'suggestion_stale') {" in html
    assert 'setSuggestionStale(true);' in html
    assert 'setSuggestionStale(!!payload.stale);' in html  # honors the server's sync-on-reconnect stale flag


def test_item5_hangup_button_disconnects_the_real_call_and_never_optimistically_claims_ended():
    """The Hangup button must request a real disconnect and show 'ending' as
    honest in-flight feedback, but the actual 'ended' state transition must
    still only ever come from the real call.on('disconnect') handler (tested
    above), never be set directly by the hangup click handler itself."""
    html = _read()
    hangup_start = html.index("els.voiceHangupBtn.addEventListener('click'")
    hangup_end = html.index('});', hangup_start)
    body = html[hangup_start:hangup_end]
    assert 'activeCall.disconnect();' in body
    assert "setCallState('ending');" in body
    assert "setCallState('ended')" not in body  # must come from the real SDK event only


def test_item6_every_call_ending_sdk_event_converges_on_the_one_cleanup_function():
    """No zombie state after any abort path (prospect hangs up, seller hangs
    up, Twilio reports cancel/reject/error) — disconnect/cancel/reject/error
    must all funnel through the SAME onCallEnded() helper, which is the one
    place `activeCall` is cleared, rather than four independent copies that
    could drift (e.g. one forgetting to null out activeCall, leaving the
    Hangup button silently pointed at a dead Call object)."""
    html = _read()
    onCallEnded_start = html.index('function onCallEnded(state, opts)')
    onCallEnded_end = html.index('\n  }\n\n  els.voiceHangupBtn', onCallEnded_start)
    onCallEnded_body = html[onCallEnded_start:onCallEnded_end]
    assert 'activeCall = null;' in onCallEnded_body
    body = _start_voice_test_call_body(html)
    for event_name in ('disconnect', 'cancel', 'reject'):
        assert f"call.on('{event_name}', function () {{ onCallEnded('ended'); }});" in body
    assert "onCallEnded('failed'" in body
