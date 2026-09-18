# REPLICA Product Specification v0.3

## 1. Produktversprechen

**REPLICA hilft einem Verkäufer während eines Cold Calls in Echtzeit und erklärt nach dem Call, was funktioniert hat, was verbessert werden kann und welches Potenzial für kommende Gespräche besteht.**

Das System passt Empfehlungen an beobachtete Sprache des Prospects an: Wortwahl, Satzlänge, Direktheit und fachliche Komplexität. Später kommen akustische Signale wie Sprechtempo, Pausen, Antwortlatenz und Overlap hinzu.

## 2. Primäre Nutzer

### Verkäufer / SDR
- möchte während eines Gesprächs sehr schnell wissen, was er als Nächstes sagen kann
- möchte nach dem Call ein kurzes, konkretes Coaching
- möchte nicht mit zehn Charts während des Calls überladen werden

### Sales Manager
- möchte verstehen, warum Ergebnisse entstehen
- möchte Ramp-up, Entwicklung und Rahmenbedingungen berücksichtigen
- möchte Coaching-Chancen erkennen, ohne REPLICA als automatischen Personalentscheider zu verwenden

### Admin / RevOps
- verbindet CRM, Kalender und Telefonie
- verwaltet Consent, Datenspeicherung und Pilotmetriken

## 3. MVP User Flows

### Flow A — Live Copilot
1. Call startet.
2. Consent-Status wird dokumentiert.
3. Audio/ASR streamt Prospect-Aussage als Interim Transcript.
4. Fast Path klassifiziert Sales-Event und Gesprächsphase frühzeitig (siehe unten).
5. LanguageSync aktualisiert Sprachprofil.
6. Prospect-Turn endet.
7. REPLICA zeigt **eine** primäre Empfehlung:
   - `SAG JETZT`
   - kurze Antwort
   - kurze Delivery-Hilfe: z. B. `kurz · ruhig`
   - `Nicht tun`
8. Verkäufer nutzt oder ignoriert Empfehlung.
9. Verkäufer bewertet Empfehlung optional mit `gut / brauchbar / falsch`.

REPLICA funktioniert bereits ab der ersten Gesprächssekunde, nicht erst ab Discovery
oder Einwandbehandlung. SalesBrain unterscheidet dafür Gesprächsphasen:
`greeting, rapport_smalltalk, transition, opening, discovery, pitch, objection,
negotiation, closing, wrap_up` (Implementierung: `app/services/sales_brain.py`,
Details/Abgrenzung: `docs/DECISIONS.md` ADR-022–025).

Für Smalltalk/Begrüßung beantwortet REPLICA konkret:
- Ist Smalltalk gerade angemessen? (nur wenn der Prospect selbst einen persönlichen
  Anker einbringt, z. B. „Ich komme gerade aus einem Meeting.“)
- Reicht eine kurze soziale Reaktion, oder passt eine kurze Folgefrage?
- Möchte der Prospect erkennbar direkt zum Anliegen kommen (z. B. „Ja, worum geht
  es?“) — dann sofort Übergang zum Business, kein Smalltalk erzwingen.
- Ist jetzt der richtige Zeitpunkt für den Übergang zum Business?

Smalltalk wird nie künstlich verlängert: Nach dem ersten Austausch verschiebt sich die
Empfehlung automatisch Richtung Übergang statt weiterer Folgefragen.

### Flow B — Post-Call Review
Unmittelbar nach dem Call:
- 1–2 Sätze Zusammenfassung
- max. 3 Stärken
- max. 3 Verbesserungen
- max. 2 verpasste Chancen
- **ein** Fokus für den nächsten Call

### Flow C — Manager View
Zeigt getrennt:
- Outcome
- Gesprächs-/Nutzungsmetriken
- Ramp-up-Kontext
- Trend
- Lead-/Kampagnenkontext, sobald verfügbar

Verboten im Produkt:
- Fire Score
- Kündigungsempfehlung
- „schlechter Verkäufer“-Label
- automatische Rangliste als Personalentscheidung

### Flow D — Outcome Linking
Cold Call wird mit folgenden Downstream-Events verknüpft:
- Meeting gebucht
- Meeting stattgefunden
- Opportunity erzeugt
- Angebot / Deal
- Closed Won / Revenue

## 4. MVP Features — Must Have

- Live Suggestion UI
- Suggestion Latency Telemetry
- LanguageSync
- Fast Sales Event Classifier
- Consent Gate
- Call/Turn/Suggestion Storage
- Suggestion Feedback
- Post-Call Review
- Manager Context View
- CRM- und Calendar-Adapter
- Experiment Assignment
- Audit Log

## 5. Should Have

- dual-channel audio
- response latency / WPM / pauses / overlap
- CRM webhooks
- meeting-held detection
- tenant-specific playbooks
- product/offer context

## 6. Not in MVP

- autonomous mass outbound calling
- biometric emotion labels
- personality inference
- automatic employment decisions
- global training on customer raw data by default
- custom TTS foundation model

## 7. Live UI Constraint

During the call the seller should see no more than:

1. **SAG JETZT:** one short phrase
2. **DELIVERY:** e.g. `kurz · ruhig`
3. **NICHT:** one short caution

All deep analysis belongs after the call.

## 8. Internal quality targets for pilot

These are engineering targets, not current measured results:
- suggestion UI P50 ≤ 500 ms after detected end-of-turn
- suggestion UI P95 ≤ 800 ms after detected end-of-turn
- 0 blocking LLM call in the Fast Path
- >99% API availability during pilot windows
- every suggestion carries provenance/evidence level

---

## 9. Global product boundary

REPLICA is shipped in four separable modes:

1. Assist — human seller + live suggestions
2. Intelligence — post-call analysis and coaching
3. Manager — contextual development and team insights
4. Agent — autonomous voice, separately controlled

`Agent` must never be assumed available globally. Availability is determined by jurisdiction/campaign policy.

## 10. Seller-protection principle

REPLICA must distinguish:
- outcome
- controllable conversation skill
- development trend
- ramp-up/product tenure
- campaign/lead context

It must not convert short-term poor results into an employment verdict.

## 11. Network Intelligence principle

Customer data remains private by default.

Cross-company learning requires separate opt-in and may expose only sufficiently aggregated, delayed and non-identifying patterns. No customer may use REPLICA to discover a named competitor's current pricing, customer list, future strategy or bid terms.
