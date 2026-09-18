from __future__ import annotations
import math
import re
from collections import Counter

GERMAN_STOP = {
    'aber','also','dann','dass','der','die','das','ein','eine','einen','einer','für','haben','hier','ich','ist',
    'mit','oder','schon','sie','sind','und','wir','was','wie','zu','zum','zur','jetzt','gerade','eigentlich'
}
COMPLEX_TERMS = {
    'implementierung','integration','skalierbarkeit','automatisierung','prozesslandschaft','entscheidungskriterien',
    'wirtschaftlichkeit','amortisation','conversion','infrastruktur','differenzierung','regelbasiert','schnittstelle',
    'opportunity','procurement','orchestrierung','transformation'
}
DIRECT_MARKERS = {'kurz','einfach','direkt','worum','sagen sie','keine zeit','wenig zeit','was bringt','was kostet'}


def tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÄÖÜäöüß0-9'-]+", text)


def lexical_complexity(text: str) -> float:
    words = tokenize(text)
    if not words:
        return 0.0
    avg_len = sum(len(w) for w in words) / len(words)
    rareish = sum(1 for w in words if len(w) >= 9) / len(words)
    complex_hits = sum(1 for w in words if w.lower() in COMPLEX_TERMS) / len(words)
    return round(min(1.0, 0.05 * max(avg_len - 4, 0) + 0.65 * rareish + 1.4 * complex_hits), 3)


def extract_mirror_terms(text: str, limit: int = 4) -> list[str]:
    words = tokenize(text)
    counts = Counter(w.lower() for w in words if len(w) >= 6 and w.lower() not in GERMAN_STOP and not w.isdigit())
    first_form: dict[str, str] = {}
    for w in words:
        first_form.setdefault(w.lower(), w)
    return [first_form[w] for w, _ in counts.most_common(limit)]


def analyze_language(text: str) -> dict:
    words = tokenize(text)
    sentence_count = max(1, len(re.findall(r'[.!?]+', text)))
    avg_sentence_words = len(words) / sentence_count
    avg_word_length = sum(len(w) for w in words) / max(len(words), 1)
    complexity_score = lexical_complexity(text)
    lower = text.lower()
    directness = 'high' if any(m in lower for m in DIRECT_MARKERS) or avg_sentence_words <= 9 else 'medium'
    if complexity_score >= 0.42:
        complexity = 'high'
    elif complexity_score >= 0.20:
        complexity = 'medium'
    else:
        complexity = 'plain'
    if directness == 'high':
        target_words = 10
    elif complexity == 'high':
        target_words = 22
    else:
        target_words = 16
    return {
        'complexity': complexity,
        'complexity_score': complexity_score,
        'directness': directness,
        'avg_sentence_words': round(avg_sentence_words, 1),
        'avg_word_length': round(avg_word_length, 1),
        'target_response_words': target_words,
        'mirror_terms': extract_mirror_terms(text),
    }


def merge_language_profile(turn_profiles: list[dict]) -> dict:
    if not turn_profiles:
        return {'complexity': 'medium', 'directness': 'medium', 'target_response_words': 16, 'mirror_terms': []}
    avg_score = sum(float(p.get('complexity_score', 0.25)) for p in turn_profiles) / len(turn_profiles)
    direct_high = sum(1 for p in turn_profiles if p.get('directness') == 'high') >= math.ceil(len(turn_profiles) / 2)
    terms: list[str] = []
    for p in reversed(turn_profiles):
        for term in p.get('mirror_terms', []):
            if term.lower() not in [x.lower() for x in terms]:
                terms.append(term)
            if len(terms) >= 6:
                break
        if len(terms) >= 6:
            break
    complexity = 'high' if avg_score >= 0.42 else 'medium' if avg_score >= 0.20 else 'plain'
    return {
        'complexity': complexity,
        'directness': 'high' if direct_high else 'medium',
        'target_response_words': 10 if direct_high else 22 if complexity == 'high' else 16,
        'mirror_terms': terms,
        'evidence': 'observed_language_only',
    }
