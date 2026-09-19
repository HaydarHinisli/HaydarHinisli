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
