from __future__ import annotations


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


def decide(text: str, language_policy: dict) -> dict:
    event = classify_sales_event(text)
    rule = PLAYBOOK[event]
    advanced = language_policy.get('complexity') == 'high'
    suggestion = rule['suggestion_advanced'] if advanced else rule['suggestion_plain']
    return {
        'event': event,
        'strategy': rule['strategy'],
        'suggestion': suggestion,
        'do_not': rule['do_not'],
        'reason': rule['reason'],
        'confidence': 0.88 if event != 'discovery' else 0.68,
    }
