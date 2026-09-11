# Übersichtspapier: Testmethoden zur Evaluation von RAG-Komponenten
**KI Servicezentrum (KISZ) | Stand: [Datum] | Version: 0.1 (Entwurf)**

---

## 1. Zielsetzung des Papiers

Dieses Papier gibt einen strukturierten Überblick über gängige Testmethoden zur Evaluation von RAG-Systemen (Retrieval-Augmented Generation), am Beispiel des SENTRA-Systems. Es soll ein **grundlegendes methodisches Verständnis** vermitteln und als **Blueprint für zukünftige KI-Projekte** im Bundestag dienen – unabhängig vom konkret eingesetzten System.

---

## 2. Kurzeinordnung: Wie funktioniert ein RAG-System?

Ein RAG-System kombiniert zwei Komponenten:

1. **Retrieval-Komponente**: Sucht relevante Dokumente/Textabschnitte aus einer Wissensbasis.
2. **Generierungskomponente**: Ein Sprachmodell formuliert auf Basis der gefundenen Abschnitte eine Antwort (inkl. Quellenangaben/Fußnoten).

Testmethoden müssen daher **beide Komponenten getrennt und im Zusammenspiel** betrachten, da ein Fehler in der Antwort sowohl aus fehlerhaftem Retrieval als auch aus fehlerhafter Generierung resultieren kann.

---

## 3. Kategorien von Testmethoden

### 3.1 Retrieval-Evaluation
Prüft, ob die *richtigen* Dokumente überhaupt gefunden werden.

- **Context Precision**: Anteil der abgerufenen Textabschnitte, die tatsächlich relevant sind.
- **Context Recall**: Anteil der relevanten Textabschnitte in der Wissensbasis, die tatsächlich gefunden wurden.
- **Ranking-Qualität**: Werden die relevantesten Abschnitte auch priorisiert angezeigt/genutzt?

### 3.2 Generierungs-Evaluation
Prüft die Qualität der vom Sprachmodell formulierten Antwort.

- **Faithfulness / Groundedness**: Stützt sich die Antwort ausschließlich auf die abgerufenen Quellen, oder werden Inhalte "erfunden" (Halluzination)?
- **Answer Relevancy**: Beantwortet die Ausgabe tatsächlich die gestellte Frage?
- **Fußnoten-/Zitationsgenauigkeit**: Stimmen die referenzierten Fußnoten inhaltlich mit der getroffenen Aussage überein und existieren sie tatsächlich?

### 3.3 End-to-End-Evaluation
Betrachtet das Gesamtsystem aus Nutzerperspektive.

- **Aufgabenerfüllung**: Löst die Antwort das eigentliche Informationsbedürfnis?
- **Konsistenzprüfung**: Führen identische oder inhaltlich gleichwertige Anfragen zu stabilen, widerspruchsfreien Antworten?
- **Prompt-Robustheit**: Bleibt die Qualität der Antwort stabil, wenn dieselbe Frage unterschiedlich formuliert wird (Tempus, Wortwahl, Umgangssprache vs. Fachsprache)?

### 3.4 Automatisierte vs. menschliche Evaluation
| | Automatisierte Metriken | Menschliche Bewertung |
|---|---|---|
| Vorteile | Skalierbar, reproduzierbar, schnell | Erfasst fachliche/inhaltliche Nuancen, Kontextwissen |
| Nachteile | Bildet fachliche Feinheiten oft nur eingeschränkt ab | Aufwändig, subjektiv, schwer skalierbar |
| Typische Werkzeuge | z. B. RAGAS, TruLens, DeepEval (LLM-als-Bewerter-Ansätze) | Strukturierte Testbögen, Expertenreview (z. B. durch WD) |

Empfehlung: **Kombination beider Ansätze** – automatisierte Metriken für laufendes Monitoring, menschliche Prüfung für inhaltlich sensible/kritische Fälle (z. B. Fußnotenkorrektheit bei parlamentarischen Anfragen).

### 3.5 Robustheits- und Stresstests
- **Prompt-Variation**: Systematisches Durchspielen unterschiedlicher Formulierungen derselben Anfrage.
- **Edge Cases**: Testen mit unklaren, mehrdeutigen oder außerhalb der Wissensbasis liegenden Fragen.
- **Regressionstests**: Wiederholte Prüfung bestehender Testfälle nach Systemupdates, um neue Fehler frühzeitig zu erkennen.

### 3.6 Red-Teaming / adversariale Tests
Gezielte Versuche, das System zu Fehlausgaben, Falschzitaten oder unangemessenen Antworten zu verleiten – wichtig insbesondere bei öffentlichkeitswirksamen oder rechtlich sensiblen Anwendungsfällen.

---

## 4. Vorschlag für ein methodisches Vorgehen im Bundestag

1. **Baseline schaffen**: Feste Menge an Referenz-Testfällen mit bekannter korrekter Antwort definieren.
2. **Laufendes Testing**: Regelmäßige Stichproben durch Hotline (breite Abdeckung) und punktuell durch WD (fachliche Tiefe).
3. **Strukturierte Dokumentation**: Einheitliche Erfassung nach festem Schema (siehe separate Vorlage für Testverfahren).
4. **Auswertung & Trendanalyse**: Regelmäßige Aggregation der Ergebnisse zur Identifikation systematischer Schwachstellen (z. B. wiederkehrende Fußnotenfehler).
5. **Rückkopplung an Systementwicklung**: Ergebnisse fließen in Priorisierung von Verbesserungsmaßnahmen ein.

---

## 5. Übertragbarkeit auf zukünftige KI-Projekte

Die hier beschriebenen Testkategorien (Retrieval, Generierung, End-to-End, automatisiert/menschlich, Robustheit, Red-Teaming) sind **nicht spezifisch für SENTRA**, sondern grundsätzlich auf jedes RAG-basierte System übertragbar. Für neue Projekte wird empfohlen:

- Frühzeitige Festlegung von Testkategorien bereits in der Konzeptionsphase.
- Aufbau eines Referenz-Testfallkatalogs parallel zur Systementwicklung.
- Nutzung derselben Dokumentationsstruktur, um Vergleichbarkeit zwischen Projekten und Einheiten zu ermöglichen.

---

## 6. Offene Punkte / Abstimmungsbedarf

- [ ] Auswahl konkreter Tool-Unterstützung für automatisierte Metriken (z. B. Prüfung von RAGAS/TruLens auf Einsatzfähigkeit in der Bundestags-IT-Umgebung)
- [ ] Festlegung, welche Metriken verpflichtend vs. optional erhoben werden
- [ ] Abgleich mit Datenschutz-/IT-Sicherheitsanforderungen bei Einsatz externer Evaluationswerkzeuge

---

*Dieses Dokument ist ein erster Entwurf und dient als Diskussionsgrundlage für KISZ, Hotline und WD.*
