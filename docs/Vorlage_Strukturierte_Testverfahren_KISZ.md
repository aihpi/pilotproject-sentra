# Vorlage für strukturierte Testverfahren – SENTRA-System
**KI Servicezentrum (KISZ) | Stand: 28.08.2026 | Version: 0.3 (Entwurf)**

---

## 1. Zweck der Vorlage

Diese Vorlage beschreibt, wie Hotline und WD das SENTRA-System systematisch testen, welche Techniken dabei zum Einsatz kommen und wie sich automatisierte Vorprüfung und menschliche Bewertung sinnvoll kombinieren lassen. Ziel ist eine belastbare, wiederholbare Testpraxis, die Inkonsistenzen in den Ausgaben (insbesondere bei Fußnoten) und Instabilitäten bei Prompt-Variationen zuverlässig aufdeckt, ohne dass jede einzelne Ausgabe manuell gelesen werden muss.

---

## 2. Grundprinzip: automatisierte Vorprüfung, menschliche Letztentscheidung

Reine Textabgleiche, etwa ob mehrere Antworten übereinstimmen oder eine Fußnote existiert, lassen sich automatisiert vorprüfen. Fachliche Einschätzungen, etwa ob eine Quelle eine Aussage wirklich stützt, bleiben in menschlicher Hand.

Der Testprozess ist deshalb dreistufig aufgebaut:

**Stufe 1 – Automatisierte Vorprüfung**
Skripte und ein LLM-Prüfmodell laufen über alle Testfälle und markieren auffällige Fälle. Diese Stufe deckt die Breite ab.

**Stufe 2 – Menschliche Prüfung der markierten Fälle**
Hotline und WD prüfen gezielt die von Stufe 1 markierten Fälle sowie alle Grenzfälle, die grundsätzlich nicht vorgefiltert werden. Diese Stufe sorgt für die fachliche Tiefe.

**Stufe 3 – Stichprobenkontrolle**
Ein kleiner Zufallsanteil der von Stufe 1 als unauffällig eingestuften Fälle wird trotzdem manuell nachgeprüft. Damit lässt sich erkennen, ob das Prüfmodell systematisch etwas übersieht.

```
Testfälle
   │
   ▼
Stufe 1: Skript- und LLM-Vorprüfung  ──────────────►  unauffällig
   │                                                       │
   │ auffällig                                             ▼
   ▼                                                Stufe 3: Stichprobe
Stufe 2: Manuelle Prüfung (Hotline/WD)              (z. B. 10 % der Fälle)
   │
   ▼
Dokumentation & Auswertung (KISZ)
```

---

## 3. Phase 1 – Testfälle auswählen

Ausgangsbasis sind reale, häufig gestellte Anfragen aus dem Tagesgeschäft der Hotline, etwa aus den letzten vier bis sechs Wochen. Ergänzend werden bekannte Problemfälle aus vorherigen Rückmeldungen gezielt aufgenommen, da sich dort erfahrungsgemäß Schwachstellen wiederholen.

Für eine Testrunde haben sich 15 bis 25 Testfälle als handhabbare Größe bewährt, davon mindestens fünf mit klarem Fußnoten- oder Quellenbezug, weil dort die Fehleranfälligkeit am höchsten ist. Die Testfälle werden grob nach Kategorien geordnet, etwa Gesetzgebungsverfahren, Geschäftsordnung oder Abgeordnetenrechte, damit sich später auch kategorienspezifische Muster erkennen lassen.

Jeder Testfall wird vor der Durchführung mit folgenden Angaben festgehalten. Die Test-ID setzt sich zusammen aus dem Kürzel der Kategorie und einer fortlaufenden dreistelligen Nummer, zum Beispiel GO für Geschäftsordnung, GV für Gesetzgebungsverfahren oder AR für Abgeordnetenrechte. Die Nummer wird je Kategorie fortlaufend vergeben und auch bei zurückgezogenen Testfällen nicht wiederverwendet, damit jede ID eindeutig bleibt.

| Feld                                                      | Erklärung                                                                                                                                                                             | Beispiel                                                                                               |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Test-ID                                                   | Kategorie-Kürzel + fortlaufende Nummer, z. B. GO-014 für den 14. Testfall der Kategorie Geschäftsordnung                                                                              | TF-GO-014                                                                                              |
| Kategorie                                                 | Grobe inhaltliche Einordnung, dient später der Auswertung nach Schwachstellen je Kategorie                                                                                            | Geschäftsordnung                                                                                       |
| Ausgangsfrage                                             | Die unveränderte Ursprungsfrage, wie sie später auch paraphrasiert wird (siehe 4.2)                                                                                                   | Wie lange darf ein Redner im Plenum sprechen?                                                          |
| Abteilung                                                 | Wer den Testfall eingebracht hat, wichtig für Rückfragen und zur Auswertung, welche Stelle welche Fehler häufiger findet                                                              | Hotline                                                                                                |
| Erwartete Antwort / Referenz                              | Die fachlich korrekte Antwort, formuliert bevor SENTRA getestet wird, damit die Erwartung nicht nachträglich an die tatsächliche Ausgabe angepasst wird                               | Grundsatz einer Redezeit von 15 Minuten je Fraktion nach § 35 GOBT, mit Verweis auf Ausnahmeregelungen |
| Referenzquelle (korrekt)                                  | Die Textstelle, die die erwartete Antwort tatsächlich stützt                                                                                                                          | GOBT § 35                                                                                              |
| Referenzquelle (thematisch ähnlich, aber veraltet/falsch) | Eine Quelle zum gleichen Thema, die aber falsche oder überholte Angaben enthält. Damit lässt sich prüfen, ob SENTRA versehentlich aus der falschen von zwei passenden Quellen zitiert | Alte GOBT-Fassung vor Novelle 2022, § 35 a. F. mit abweichender Redezeitregelung                       |
| Grund für Aufnahme                                        | Nur bei bekannten Problemfällen, hält fest, warum der Testfall in die Runde aufgenommen wurde                                                                                         | Vorherige SENTRA-Antwort nannte falsche Paragraphennummer                                              |

---

## 4. Phase 2 – Techniken zur Testdurchführung

Jeder Testfall wird nicht nur einmal geprüft, sondern über gezielte Varianten. Vier Techniken kommen zum Einsatz, jeweils mit Hinweis darauf, welcher Anteil automatisiert und welcher manuell erfolgt.

### 4.1 Wiederholungslauf (Konsistenzprüfung)

Derselbe Prompt wird unverändert dreimal in getrennten Sitzungen eingegeben. Statt die drei Ausgaben von Hand zu vergleichen, übernimmt ein separates LLM-Prüfmodell den ersten Abgleich: Es erhält alle drei Antworten und wird gezielt gefragt, ob sich Kernaussage, genannte Zahlen oder zitierte Quellen unterscheiden, nicht nur der Wortlaut. Weicht das Prüfmodell eine relevante inhaltliche Abweichung aus, geht der Fall in die manuelle Prüfung. Bleibt alles unauffällig, fließt der Fall in den Stichprobenpool aus Stufe 3.

*Wichtig:* Das Prüfmodell sollte nicht dasselbe Modell oder denselben Prompt-Aufbau wie SENTRA selbst verwenden, sonst überträgt sich ein mögliches Konsistenzproblem lediglich auf eine andere Stelle.

### 4.2 Prompt-Paraphrasierung (Robustheitsprüfung)

Die Varianten werden nicht von Hand formuliert, sondern zunächst von einem LLM erzeugt und anschließend von Hotline oder WD kurz gegengeprüft. Das spart Zeit gegenüber vollständig manueller Formulierung, stellt aber sicher, dass keine Variante versehentlich eine andere Frage stellt als die Ausgangsfrage. Freigegeben wird nur, was inhaltlich eindeutig dasselbe meint.

Zu jedem Testfall werden mindestens drei Formulierungsvarianten erzeugt:

| Variante          | Formulierung                                                                     |
| ----------------- | -------------------------------------------------------------------------------- |
| Umgangssprachlich | "Wie lange darf ein Redner im Plenum sprechen?"                                  |
| Fachsprachlich    | "Welche Redezeitregelung gilt gemäß Geschäftsordnung im Plenum des Bundestages?" |
| Verkürzt          | "Redezeit Plenum, Regelung?"                                                     |

Auch hier übernimmt das LLM-Prüfmodell den ersten Abgleich zwischen den drei Antworten, analog zu 4.1. Auffällige Fälle gehen an Hotline oder WD.

### 4.3 Quellenprüfung

Prüft, ob SENTRA inhaltlich die richtige Quelle herangezogen hat und ob eine zitierte Fußnote auch formal stimmt. Besonders relevant, wenn mehrere Quellen zum gleichen Thema vorliegen, von denen eine aktuell und korrekt ist und eine andere veraltet oder falsch, wie in Phase 1 mit den beiden Referenzquellen-Feldern angelegt. Die Prüfung läuft in drei Schritten, vom mechanischen zum fachlichen:

**a) Existenz- und Zitatprüfung.** Nur relevant, wenn SENTRA wörtlich zitiert. Ein Skript ruft die referenzierte Textstelle im Ursprungsdokument ab und prüft, ob die Fußnote existiert und ob der zitierte Text tatsächlich dort steht. Reiner Textabgleich, vollständig automatisierbar.

**b) Quellenauswahl.** Zitiert SENTRA die als korrekt hinterlegte Referenzquelle, oder greift es versehentlich auf die thematisch ähnliche, aber veraltete oder falsche Quelle zurück? Lässt sich teilweise automatisiert vorprüfen, indem die zitierte Quelle mit der hinterlegten korrekten Referenzquelle abgeglichen wird.

**c) Kontextprüfung.** Gibt die herangezogene Quelle die getroffene Aussage inhaltlich richtig wieder, wörtlich zitiert oder paraphrasiert? Bleibt in menschlicher Hand, da hier eine fachliche Einschätzung gefragt ist, gerade bei Paraphrasen, wo kein einfacher Textabgleich möglich ist.

Jede Fußnote erhält am Ende eine Gesamtbewertung: korrekt, Quelle falsch/veraltet, oder Quelle stützt Aussage nicht.

### 4.4 Grenzfall-Test (Edge Cases)

Gezielt werden Testfälle eingebaut, die außerhalb der Wissensbasis liegen, mehrdeutig formuliert sind oder veraltete Sachverhalte betreffen. Diese Kategorie wird grundsätzlich nicht automatisiert vorgefiltert und geht immer direkt an Hotline oder WD, da hier das eigentliche Risiko liegt und eine automatisierte Einstufung wenig Aussagekraft hätte.

---

## 5. Phase 3 – Bewertung

Für jede Ausgabe wird festgehalten, ob die Kernaussage inhaltlich korrekt ist, ob die Quellenprüfung (4.3) unauffällig ist, ob die Aussage über die geprüften Varianten stabil bleibt und, bei Grenzfällen, ob das System die Unsicherheit angemessen kennzeichnet, statt eine Antwort zu erfinden.

Bei Abweichungen wird der Schweregrad eingestuft:

| Stufe | Bezeichnung | Beispiel                                                                    |
| ----- | ----------- | --------------------------------------------------------------------------- |
| 1     | Geringfügig | Stilistische Abweichung, Kernaussage unverändert                            |
| 2     | Moderat     | Fußnote ungenau, Kernaussage korrekt                                        |
| 3     | Erheblich   | Fußnote falsch oder nicht auffindbar; oder falsche/veraltete Quelle zitiert |
| 4     | Kritisch    | Inhaltlich falsche oder erfundene Aussage                                   |

Fälle mit Schweregrad 3 oder 4 werden unabhängig davon, ob sie über Stufe 2 (als auffällig markiert) oder Stufe 3 (Stichprobe) in die manuelle Prüfung gelangt sind, gesondert an KISZ gemeldet.

---

## 6. Phase 4 – Dokumentation je Testfall

| Feld | Eintrag |
|---|---|
| Test-ID | |
| Datum | |
| Tester/in | |
| Kategorie | |
| Angewendete Technik(en) | |
| Ursprünglicher Prompt | |
| Geprüfte Varianten (Wortlaut) | |
| Varianten erstellt durch | LLM (Erststellung) |
| Varianten freigegeben durch | Hotline / WD |
| Automatisiert geprüft durch | Skript / LLM-Prüfmodell / entfällt |
| Ergebnis Automatikprüfung | unauffällig / auffällig, siehe Anmerkung |
| Gefunden über | Stufe 2 (auffällig markiert) / Stufe 3 (Stichprobe) / Grenzfall (immer manuell, 4.4) |
| Manuell geprüft durch | Hotline / WD / entfällt |
| Kernbefund je Variante | |
| Quellenbewertung (4.3a Existenz/Zitat) | existiert & stimmt überein / weicht ab / existiert nicht / entfällt (keine wörtl. Zitate) |
| Quellenbewertung (4.3b Quellenauswahl) | korrekte Quelle / falsche bzw. veraltete Quelle |
| Quellenbewertung (4.3c Kontextprüfung) | Quelle stützt Aussage / stützt Aussage nicht |
| Schweregrad (1–4) | |
| Reproduzierbar? | einmalig / wiederholt / entfällt (nur ein Lauf vorhanden) |
| Freitext-Anmerkung | |

Ausgefüllte Bögen gehen an [zentrale Ablage]. KISZ führt sie in regelmäßigem Turnus, etwa monatlich, zu einer Trendauswertung zusammen: Wo häufen sich Fußnotenfehler, wo werden falsche oder veraltete Quellen zitiert, welche Kategorien sind instabil, und wie oft weicht die Automatikprüfung von der späteren manuellen Einschätzung ab. Letzteres ist die wichtigste Kennzahl, um zu beurteilen, ob sich die Prüfschwelle in Stufe 1 zu großzügig oder zu streng eingestellt ist.

---

## 7. Offene Punkte / Abstimmungsbedarf

- Festlegung der zentralen Ablage, etwa gemeinsames Laufwerk oder Ticket-System
- Turnus für Testrunden und für die Sammelauswertung
- Klärung, ob WD standardmäßig oder nur bei fachlich anspruchsvollen Fällen einbezogen wird
- Auswahl und technische Anbindung eines geeigneten LLM-Prüfmodells, unabhängig von SENTRA selbst
- Festlegung der Stichprobenquote für Stufe 3, als Ausgangspunkt bietet sich ein Anteil von 10 Prozent an
- Abstimmung mit KISZ, ob die skriptgestützte Fußnotenprüfung technisch im laufenden Betrieb umsetzbar ist

---

*Dieses Dokument ist ein überarbeiteter Entwurf (v0.3) mit Schwerpunkt auf einem zweistufigen Zusammenspiel aus automatisierter Vorprüfung und menschlicher Bewertung und wird nach Rückmeldung durch KISZ, Hotline und WD weiter angepasst.*


- Feature: add new categories to old documents
- Document:
	- Catalogue schicken
	- 