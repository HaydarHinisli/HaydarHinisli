from __future__ import annotations

# Full conversation-phase taxonomy (see docs/DECISIONS.md ADR-022). 'opening' is kept
# for schema completeness but is not auto-detected from prospect text alone in this
# Fast Path — it is naturally the seller's own next move right after 'transition',
# and a stateless single-utterance heuristic has no reliable way to tell "the seller
# is opening" from "the seller is doing discovery" without call-level state (Sprint 2+
# once real per-call turn sequencing/state exists).
CONVERSATION_PHASES = (
    'greeting', 'rapport_smalltalk', 'transition', 'opening', 'discovery',
    'pitch', 'objection', 'negotiation', 'closing', 'wrap_up',
)

GREETING_MARKERS = ('hallo', 'guten tag', 'guten morgen', 'guten abend', 'servus', 'moin')

# Personal/non-business anchors the PROSPECT brought up themselves. Per the product
# brief: only ever react to anchors the prospect introduces in the current call, never
# invent or presume personal context.
SMALLTALK_MARKERS = (
    'meeting', 'termin gerade', 'wochenende', 'urlaub', 'wetter', 'gerade unterwegs',
    'wie geht es ihnen', 'wie geht’s ihnen', 'wie gehts', 'schönen tag', 'stressig',
    'viel zu tun', 'gerade rausgefahren', 'komme gerade', 'bin gerade',
)

DIRECT_TO_BUSINESS_MARKERS = (
    'worum geht es', 'worum geht\'s', 'was wollen sie', 'kommen sie zum punkt',
    'was kann ich für sie tun', 'worum handelt es sich', 'ja, worum',
)

NEGOTIATION_MARKERS = ('rabatt', 'konditionen', 'nachlass', 'vertragslaufzeit', 'staffelpreis', 'verhandeln')

CLOSING_MARKERS = (
    'geht es weiter', 'nächste schritte', 'nächsten schritte', 'schicken sie mir den vertrag',
    'wann können wir starten', 'termin vereinbaren', 'lassen sie uns einen termin',
)

WRAP_UP_MARKERS = (
    'vielen dank für ihre zeit', 'danke für ihre zeit', 'ich melde mich',
    'auf wiederhören', 'tschüss', 'bis dann', 'schönen tag noch', 'wir hören uns',
)

# sales_events that already have dedicated, tested PLAYBOOK entries — these map onto
# phase='objection' and are never re-routed through PHASE_PLAYBOOK (see decide()).
OBJECTION_EVENTS = {'time_pressure', 'email_exit', 'no_interest', 'existing_supplier', 'price', 'authority'}


def classify_sales_event(text: str) -> str:
    lower = text.lower()
    if any(x in lower for x in ['keine zeit','wenig zeit','muss weiter','gleich einen termin','bin im termin']):
        return 'time_pressure'
    if any(x in lower for x in ['schicken sie','per mail','eine mail','informationen schicken']):
        return 'email_exit'
    if any(x in lower for x in ['kein interesse','nicht interessiert','brauchen wir nicht']):
        return 'no_interest'
    if any(x in lower for x in ['haben schon','bereits einen','bestehenden anbieter','anderen anbieter','arbeiten mit','schon eine lösung']):
        return 'existing_supplier'
    if any(x in lower for x in ['zu teuer','kein budget','budget','preis','kostet']):
        return 'price'
    if any(x in lower for x in ['nicht zuständig','falscher ansprechpartner','entscheidet bei uns','zuständig ist']):
        return 'authority'
    if any(x in lower for x in ['wann','wie unterscheidet','wie funktioniert','was genau','was bringt']) or '?' in text:
        return 'question'
    return 'discovery'


PLAYBOOK = {
    'time_pressure': {
        'strategy': 'permission_and_relevance',
        'suggestion_plain': 'Klar. Darf ich in einem Satz prüfen, ob es überhaupt relevant ist?',
        'suggestion_advanced': 'Verstanden. Darf ich in einem Satz prüfen, ob es für Ihren aktuellen Prozess überhaupt relevant ist?',
        'do_not': 'Nicht in einen längeren Pitch wechseln.',
        'reason': 'Der Prospect signalisiert Zeitdruck. Erst Gesprächserlaubnis und Relevanz sichern.',
    },
    'email_exit': {
        'strategy': 'qualify_email_request',
        'suggestion_plain': 'Gerne. Was müsste in der Mail stehen, damit sie für Sie relevant ist?',
        'suggestion_advanced': 'Gerne. Welcher Aspekt müsste in der Mail konkret adressiert sein, damit sie für Sie relevant ist?',
        'do_not': 'Nicht kommentarlos Unterlagen schicken.',
        'reason': 'Die Mail-Anfrage kann ein höflicher Ausstieg sein. Eine kurze Frage prüft echte Relevanz.',
    },
    'no_interest': {
        'strategy': 'separate_reflex_from_rejection',
        'suggestion_plain': 'Verstanden. Ist das Thema grundsätzlich irrelevant oder nur gerade kein Schwerpunkt?',
        'suggestion_advanced': 'Verstanden. Ist das Thema für Sie grundsätzlich nicht relevant oder aktuell nur nicht priorisiert?',
        'do_not': 'Nicht gegen die Ablehnung argumentieren.',
        'reason': 'Eine kurze Klärungsfrage trennt spontane Abwehr von echter Nicht-Relevanz.',
    },
    'existing_supplier': {
        'strategy': 'discover_buying_criteria',
        'suggestion_plain': 'Was ist Ihnen bei Ihrer aktuellen Lösung am wichtigsten?',
        'suggestion_advanced': 'Welche Kriterien waren bei der Auswahl Ihrer aktuellen Lösung ausschlaggebend?',
        'do_not': 'Den bestehenden Anbieter nicht schlechtreden.',
        'reason': 'Ein bestehender Anbieter ist zuerst Informationsquelle, nicht automatisch ein finales Nein.',
    },
    'price': {
        'strategy': 'reestablish_value_before_price',
        'suggestion_plain': 'Woran würden Sie merken, dass sich die Lösung für Sie lohnt?',
        'suggestion_advanced': 'An welcher wirtschaftlichen Wirkung würden Sie festmachen, ob sich die Investition für Sie rechnet?',
        'do_not': 'Preis nicht reflexartig verteidigen oder rabattieren.',
        'reason': 'Vor Preisverteidigung muss klar sein, welcher Nutzen für den Prospect zählt.',
    },
    'authority': {
        'strategy': 'map_decision_process',
        'suggestion_plain': 'Wer beschäftigt sich bei Ihnen damit?',
        'suggestion_advanced': 'Wer verantwortet dieses Thema bei Ihnen fachlich beziehungsweise wirtschaftlich?',
        'do_not': 'Nicht versuchen, den falschen Ansprechpartner zu überzeugen.',
        'reason': 'Die nächste sinnvolle Aktion ist, den Entscheidungsweg zu verstehen.',
    },
    'question': {
        'strategy': 'answer_then_return_to_discovery',
        'suggestion_plain': 'Kurz gesagt: Wir passen die Gesprächshilfe laufend an. Wie lösen Sie das heute?',
        'suggestion_advanced': 'Der Unterschied ist die laufende Kontextanpassung statt starrer Regeln. Wie ist Ihr Prozess heute aufgebaut?',
        'do_not': 'Nicht in einen Monolog wechseln.',
        'reason': 'Die Frage verdient eine Antwort, danach sollte das Gespräch wieder in Discovery zurückgeführt werden.',
    },
    'discovery': {
        'strategy': 'advance_discovery',
        'suggestion_plain': 'Was ist dabei heute der größte Aufwand für Sie?',
        'suggestion_advanced': 'Wo entsteht in Ihrem aktuellen Prozess heute der größte operative Aufwand?',
        'do_not': 'Nicht zu früh pitchen.',
        'reason': 'Ohne klaren Bedarf ist eine kurze Discovery-Frage meist wertvoller als weitere Produktargumente.',
    },
}


# Phase-specific responses for conversational moments the objection playbook above
# doesn't cover: the very start and end of a call, prospect-initiated smalltalk, the
# hand-off from smalltalk into business, and price/terms negotiation once a prospect
# is already engaged (as opposed to a first price objection, which stays in PLAYBOOK).
PHASE_PLAYBOOK = {
    'greeting': {
        'strategy': 'greeting_and_permission',
        'suggestion_plain': 'Guten Tag, hier ist Ihr Ansprechpartner von REPLICA. Passt es gerade kurz?',
        'suggestion_advanced': 'Guten Tag, hier ist Ihr Ansprechpartner von REPLICA. Passt es Ihnen gerade für zwei Minuten?',
        'do_not': 'Nicht sofort in den Pitch starten.',
        'reason': 'Der Anruf beginnt; zuerst kurz grüßen und die Gesprächserlaubnis einholen.',
    },
    'rapport_smalltalk': {
        'strategy': 'brief_social_reaction_then_prepare_transition',
        'suggestion_plain': 'Klingt nach viel – kurz durchatmen. Darf ich trotzdem kurz sagen, worum es geht?',
        'suggestion_advanced': 'Das klingt nach einem vollen Tag. Darf ich trotzdem kurz skizzieren, worum es bei meinem Anruf geht?',
        'do_not': 'Smalltalk nicht künstlich verlängern oder erzwingen.',
        'reason': 'Der Prospect hat selbst einen persönlichen Gesprächsanker eingebracht; eine kurze, echte Reaktion wahrt Rapport, ohne den Anruf unnötig zu verzögern.',
    },
    'transition': {
        'strategy': 'transition_to_business',
        'suggestion_plain': 'Klar, ich mache es kurz: Ich rufe an, weil wir Vertriebsteams helfen, mehr qualifizierte Termine zu erzielen.',
        'suggestion_advanced': 'Gerne, ich fasse den Anlass meines Anrufs in einem Satz zusammen: Wir helfen Vertriebsteams, aus Telefonaten mehr qualifizierte Termine zu machen.',
        'do_not': 'Nicht zurück in Smalltalk wechseln.',
        'reason': 'Der Prospect signalisiert, direkt zum geschäftlichen Anliegen kommen zu wollen.',
    },
    'negotiation': {
        'strategy': 'trade_concessions_for_commitment',
        'suggestion_plain': 'Was müsste für Sie drin sein, damit wir uns einig werden?',
        'suggestion_advanced': 'Welche Konditionen wären für Sie entscheidend, damit eine Einigung für beide Seiten passt?',
        'do_not': 'Nicht als Erstes von sich aus einen Rabatt anbieten.',
        'reason': 'Vor jedem Zugeständnis sollte klar sein, welche Gegenleistung oder Verbindlichkeit der Prospect anbietet.',
    },
    'closing': {
        'strategy': 'confirm_concrete_next_step',
        'suggestion_plain': 'Dann schlage ich vor: Ich schicke Ihnen einen Terminvorschlag, passt das?',
        'suggestion_advanced': 'Dann schlage ich einen konkreten nächsten Schritt vor: einen Termin zur Vertiefung. Passt Ihnen das?',
        'do_not': 'Nicht ohne konkreten nächsten Schritt auflegen.',
        'reason': 'Der Prospect signalisiert Bereitschaft; jetzt zählt ein konkreter, terminierter nächster Schritt.',
    },
    'wrap_up': {
        'strategy': 'confirm_and_close_politely',
        'suggestion_plain': 'Danke für Ihre Zeit, ich schicke Ihnen die Zusammenfassung per Mail.',
        'suggestion_advanced': 'Vielen Dank für Ihre Zeit. Ich fasse die nächsten Schritte kurz schriftlich zusammen und sende sie Ihnen.',
        'do_not': 'Nicht kurz vor Schluss noch neue Themen eröffnen.',
        'reason': 'Der Prospect beendet das Gespräch; ein kurzer, verbindlicher Abschluss sichert die vereinbarten nächsten Schritte.',
    },
}


def analyze_smalltalk(text: str, *, turn_index: int = 0) -> dict:
    """Answers the specific questions the product brief calls out: is smalltalk
    appropriate right now, does the prospect want to skip straight to business, should
    the seller give only a brief reaction, ask a short follow-up, or transition now.

    Stateless heuristic (like the rest of the Fast Path): `turn_index` is the
    prospect's turn number within the call, used only to avoid prolonging smalltalk
    past a first exchange — it never invents a personal anchor the prospect didn't
    bring up themselves.
    """
    lower = text.lower()
    wants_business = any(m in lower for m in DIRECT_TO_BUSINESS_MARKERS)
    has_smalltalk_anchor = any(m in lower for m in SMALLTALK_MARKERS)
    smalltalk_appropriate = has_smalltalk_anchor and not wants_business

    return {
        'smalltalk_appropriate': smalltalk_appropriate,
        'prospect_wants_business': wants_business,
        'suggest_brief_reaction': smalltalk_appropriate,
        'suggest_follow_up_question': smalltalk_appropriate and turn_index <= 1,
        'suggest_transition_now': wants_business or (smalltalk_appropriate and turn_index >= 1),
    }


def detect_special_phase(text: str, *, turn_index: int = 0) -> str | None:
    """Checks for greeting/smalltalk/transition/negotiation/closing/wrap_up signals.
    Returns None when nothing special is detected, so the caller falls back to
    ordinary objection/discovery handling."""
    lower = text.lower()
    if any(m in lower for m in WRAP_UP_MARKERS):
        return 'wrap_up'
    if any(m in lower for m in CLOSING_MARKERS):
        return 'closing'
    if any(m in lower for m in NEGOTIATION_MARKERS):
        return 'negotiation'
    if any(m in lower for m in DIRECT_TO_BUSINESS_MARKERS):
        return 'transition'
    if any(m in lower for m in SMALLTALK_MARKERS):
        return 'rapport_smalltalk'
    if turn_index == 0 and len(text.split()) <= 6 and any(m in lower for m in GREETING_MARKERS):
        return 'greeting'
    return None


def decide(text: str, language_policy: dict, *, turn_index: int = 0) -> dict:
    """Chooses the response strategy. Priority order (see docs/DECISIONS.md ADR-022):

    1. A specific objection/exit event (time_pressure, email_exit, no_interest,
       existing_supplier, price, authority) always wins — these have dedicated,
       tested PLAYBOOK entries and must behave exactly as before this feature existed.
    2. Only the two generic fallback events (discovery, question) are checked for a
       more specific conversational-moment phase (greeting/smalltalk/transition/
       negotiation/closing/wrap_up) before falling back to their own PLAYBOOK entry.

    This ordering means adding phase awareness can only ever make a *generic* response
    more specific — it can never override an already-specific objection response.
    """
    event = classify_sales_event(text)
    smalltalk = analyze_smalltalk(text, turn_index=turn_index)

    if event in OBJECTION_EVENTS:
        phase = 'objection'
        rule = PLAYBOOK[event]
    else:
        special_phase = detect_special_phase(text, turn_index=turn_index)
        if special_phase:
            phase = special_phase
            rule = PHASE_PLAYBOOK[special_phase]
        else:
            phase = 'pitch' if event == 'question' else event  # event == 'discovery'
            rule = PLAYBOOK[event]

    advanced = language_policy.get('complexity') == 'high'
    suggestion = rule['suggestion_advanced'] if advanced else rule['suggestion_plain']
    return {
        'event': event,
        'phase': phase,
        'strategy': rule['strategy'],
        'suggestion': suggestion,
        'do_not': rule['do_not'],
        'reason': rule['reason'],
        'confidence': 0.88 if event != 'discovery' else 0.68,
        'smalltalk': smalltalk,
    }
