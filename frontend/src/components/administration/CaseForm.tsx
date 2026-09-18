import { cloneElement, useId, useState } from "react";
import type { CaseDraft } from "@/types";

/** Writing or changing one test case.
 *
 *  The field order is the order somebody thinks in: what was asked, what a
 *  right answer contains, what it rests on, and only then the bookkeeping.
 *
 *  Two rules are enforced here rather than left to the server, because finding
 *  out at approval time — weeks later, in front of somebody who did not write
 *  the case — is the expensive version of the same error:
 *
 *    an expected answer is always required
 *    a correct source is required unless this is a Grenzfall, which by
 *    construction has none
 *
 *  The second is the one that used to be wrong in the other direction: #130
 *  demanded a source for a Grenzfall too, which made technique 4.4 impossible
 *  to reach. So the requirement follows the checkbox rather than the field. */
export function CaseForm({
  initial,
  categories,
  editingApproved,
  onSubmit,
  onCancel,
  submitting,
}: {
  initial: CaseDraft;
  categories: string[];
  /** The latest version is approved, so this will add a new version rather
   *  than change what any past round measured against. Said plainly, because
   *  an "edit" that silently forks would be surprising the other way. */
  editingApproved: boolean;
  onSubmit: (draft: CaseDraft) => void;
  onCancel: () => void;
  submitting: boolean;
}) {
  const [draft, setDraft] = useState<CaseDraft>(initial);

  function set<K extends keyof CaseDraft>(key: K, value: CaseDraft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  const missingAnswer = !draft.erwartete_antwort.trim();
  const missingSource = !draft.grenzfall && !draft.referenz_korrekt.trim();
  const incomplete =
    !draft.ausgangsfrage.trim() || missingAnswer || missingSource;

  return (
    <form
      className="space-y-3 rounded-lg border bg-card p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!incomplete) onSubmit(draft);
      }}
    >
      {editingApproved && (
        <p className="rounded-md bg-muted/50 p-2 text-xs text-muted-foreground">
          Dieser Testfall ist freigegeben. Änderungen legen eine neue Version an
          — die bisherige bleibt unverändert, weil abgeschlossene Runden gegen
          sie gemessen haben.
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
        <Field label="Kategorie">
          <select
            value={draft.kategorie}
            onChange={(e) => set("kategorie", e.target.value)}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          >
            {categories.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Abteilung / Fachbereich">
          <input
            value={draft.abteilung}
            onChange={(e) => set("abteilung", e.target.value)}
            placeholder="z. B. Hotline"
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          />
        </Field>
      </div>

      <Field
        label="Ausgangsfrage"
        hint="So gestellt, wie sie tatsächlich gestellt wurde."
      >
        <textarea
          value={draft.ausgangsfrage}
          onChange={(e) => set("ausgangsfrage", e.target.value)}
          rows={2}
          className="w-full rounded-md border bg-background px-2 py-1 text-xs"
        />
      </Field>

      <Field
        label="Erwartete Antwort"
        hint="Vor dem Test formulieren. Eine Erwartung, die nachträglich an die Ausgabe angepasst wird, misst nichts."
        problem={
          missingAnswer
            ? "Ohne erwartete Antwort kann nicht freigegeben werden."
            : null
        }
      >
        <textarea
          value={draft.erwartete_antwort}
          onChange={(e) => set("erwartete_antwort", e.target.value)}
          rows={3}
          className="w-full rounded-md border bg-background px-2 py-1 text-xs"
        />
      </Field>

      <label className="flex items-center gap-2 text-xs">
        <input
          type="checkbox"
          checked={draft.grenzfall}
          onChange={(e) => set("grenzfall", e.target.checked)}
        />
        <span className="font-medium">Grenzfall</span>
        <span className="text-muted-foreground">
          Der Bestand deckt die Frage bewusst nicht ab; SENTRA soll die Antwort
          verweigern. Braucht keine korrekte Quelle.
        </span>
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label="Korrekte Quelle"
          hint="Wie ein Mensch sie liest, z. B. „GOBT § 35“."
          problem={
            missingSource
              ? "Pflicht, außer bei einem Grenzfall — dann bitte oben ankreuzen."
              : null
          }
        >
          <input
            value={draft.referenz_korrekt}
            onChange={(e) => set("referenz_korrekt", e.target.value)}
            disabled={draft.grenzfall}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs disabled:opacity-50"
          />
        </Field>

        <Field
          label="Aktenzeichen der korrekten Quelle"
          hint="Nur hierauf prüft 4.3b automatisch."
        >
          <input
            value={draft.referenz_korrekt_az}
            onChange={(e) => set("referenz_korrekt_az", e.target.value)}
            placeholder="WD 3 - 3000 - 029/23"
            disabled={draft.grenzfall}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs disabled:opacity-50"
          />
        </Field>

        <Field
          label="Veraltete / ähnliche Quelle"
          hint="Optional, aber sie macht 4.3b aussagekräftig."
        >
          <input
            value={draft.referenz_falsch}
            onChange={(e) => set("referenz_falsch", e.target.value)}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          />
        </Field>

        <Field label="Aktenzeichen der veralteten Quelle">
          <input
            value={draft.referenz_falsch_az}
            onChange={(e) => set("referenz_falsch_az", e.target.value)}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          />
        </Field>
      </div>

      <Field label="Grund für die Aufnahme">
        <input
          value={draft.grund_fuer_aufnahme}
          onChange={(e) => set("grund_fuer_aufnahme", e.target.value)}
          placeholder="häufige Frage, bekannte Schwachstelle, Beschwerde …"
          className="w-full rounded-md border bg-background px-2 py-1 text-xs"
        />
      </Field>

      <div className="flex items-center gap-2">
        <button
          type="submit"
          disabled={incomplete || submitting}
          className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
        >
          {editingApproved ? "Neue Version anlegen" : "Speichern"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border px-3 py-1.5 text-xs"
        >
          Abbrechen
        </button>
      </div>
    </form>
  );
}

/** A labelled control with its guidance attached as a *description*.
 *
 *  The hint sits outside the `<label>` and is wired up with
 *  `aria-describedby`. Wrapping both inside the label was simpler and wrong:
 *  the accessible name of the field became "Erwartete Antwort Vor dem Test
 *  formulieren. Eine Erwartung, die …", which is what a screen reader
 *  announces every time focus lands there. A name names; a description
 *  explains. */
function Field({
  label,
  hint,
  problem,
  children,
}: {
  label: string;
  hint?: string;
  problem?: string | null;
  children: React.ReactElement<{ id?: string; "aria-describedby"?: string }>;
}) {
  const id = useId();
  const noteId = `${id}-note`;
  const note = problem ?? hint;

  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs font-medium">
        {label}
      </label>
      {cloneElement(children, {
        id,
        ...(note ? { "aria-describedby": noteId } : {}),
      })}
      {note && (
        <span
          id={noteId}
          className={
            problem
              ? "block text-[11px] text-destructive"
              : "block text-[11px] text-muted-foreground"
          }
        >
          {note}
        </span>
      )}
    </div>
  );
}
