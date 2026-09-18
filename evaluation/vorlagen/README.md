# Vorlagen für die Erfassung von Testfällen

Diese beiden Dateien sind für die Personen, die die Testfälle zusammentragen.
Sie setzen keinen Zugang zu SENTRA und keine Kenntnis des Systems voraus.

| Datei | wofür |
|---|---|
| `SENTRA-Testfaelle-Erfassung.xlsx` | viele Fälle auf einmal — eine Zeile je Testfall, mit Auswahllisten und einem Hinweisblatt |
| `SENTRA-Testfall-Erfassung.docx` | ein einzelner Fall — ausfüllbares Formular mit Erläuterung an jedem Feld |

## Die wichtigste Regel

**Die erwartete Antwort muss feststehen, bevor SENTRA die Frage gestellt
bekommt.** Wird sie nachträglich an die tatsächliche Ausgabe angepasst, misst
der Testfall nichts mehr. Das ist keine Formalie: der gesamte Prüfbericht einer
Runde beruht darauf, und die Prüfkette wird automatisch als nicht belastbar
markiert, wenn ein Testfall erst nach dem Start der Runde freigegeben wurde.

## Was nicht ausgefüllt wird

**Test-ID** vergibt das System und benutzt sie nie ein zweites Mal, auch bei
zurückgezogenen Testfällen nicht. Eine von Hand eingetragene Nummer ist der Weg,
auf dem eine Nummer doppelt vergeben wird.

**Status** entscheidet die fachliche Durchsicht. Alles, was über diese Vorlagen
hereinkommt, ist zunächst ein Entwurf — auch wenn es vollständig ausgefüllt ist.

## Grenzfälle

Ein Grenzfall ist eine Frage, die der Bestand bewusst nicht abdeckt und bei der
SENTRA die Antwort verweigern soll. Er braucht **keine korrekte Quelle** — es
gibt keine. Er braucht aber eine erwartete Antwort, nämlich die Feststellung,
dass keine Antwort erwartet wird und warum.

Grenzfälle gehen immer an eine Person und werden nie automatisch herausgefiltert.
Sie sind die riskanteste Kategorie: ein System, das etwas erfindet, ist
schlimmer als eines, das nichts findet.

## Wie ein ausgefülltes Blatt ins System kommt

```bash
docker compose exec eval-harness \
  uv run --no-dev python -m sentra_eval.cli import /app/ausgefuellt.xlsx
```

`import` liest `.xlsx` und `.yaml` gleichermaßen. Fehlende Pflichtangaben werden
mit Zeilennummer gemeldet, und zwar so, wie Excel die Zeilen zählt.

## Diese Dateien werden erzeugt, nicht bearbeitet

```bash
cd evaluation && uv run --extra vorlagen python -m sentra_eval.cli vorlagen vorlagen
```

Beide Vorlagen entstehen aus `FIELDS` in `src/sentra_eval/vorlagen.py`. Wer ein
Feld ergänzen will, ändert es dort und erzeugt die Dateien neu — sonst laufen
Tabelle, Formular und Importer auseinander. Ein Test hält `FIELDS` gegen das
Modell des Importers.

Sie liegen trotzdem im Repository, weil die Personen, die sie brauchen, keinen
Checkout haben.
