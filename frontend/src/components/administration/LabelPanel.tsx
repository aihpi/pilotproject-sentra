import { useState } from "react";
import type { EvalCase, LabelValues } from "@/types";
import { setLabels, setTag } from "@/lib/evalApi";

const DIMENSIONS = [
  { key: "kategorie", label: "Bereich" },
  { key: "testart", label: "Testart" },
  { key: "frageform", label: "Frageform" },
  { key: "herkunft", label: "Herkunft" },
] as const;

type Dimension = (typeof DIMENSIONS)[number]["key"];

/** A case's tag and labels, editable (#288).
 *
 *  Inputs with a suggestion list rather than dropdowns: Bereich and Testart
 *  are open lists (#286), so the usual values are offered and a new one is
 *  just typed. A value nobody uses any more drops out of the suggestions by
 *  itself.
 *
 *  Labels change nothing that was measured, so saving creates no version. The
 *  number is not editable at all: everything else points at it. */
export function LabelPanel({
  entry,
  offered,
  onSaved,
}: {
  entry: EvalCase;
  offered: LabelValues;
  onSaved: () => void;
}) {
  const initial: Record<Dimension, string> = {
    kategorie: entry.kategorie,
    testart: entry.testart ?? "",
    frageform: entry.frageform ?? "",
    herkunft: entry.herkunft ?? "",
  };
  const [values, setValues] = useState(initial);
  const [tag, setTagValue] = useState(entry.tag);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const changedLabels = Object.fromEntries(
    DIMENSIONS.filter(({ key }) => values[key] !== initial[key]).map(({ key }) => [
      key,
      values[key],
    ]),
  );
  const tagChanged = tag.trim() !== entry.tag;
  const dirty = tagChanged || Object.keys(changedLabels).length > 0;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      // Labels first: with a generated tag they choose the new one, and a tag
      // typed in here should be the last word.
      if (Object.keys(changedLabels).length > 0) {
        await setLabels(entry.nummer, changedLabels);
      }
      if (tagChanged) await setTag(entry.nummer, tag.trim());
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const listId = (key: Dimension) => `labels-${entry.nummer}-${key}`;

  return (
    <div className="space-y-2 rounded-md border bg-muted/20 p-3 text-xs">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span className="font-medium">Nr.</span>
          <span className="py-1 tabular-nums">{entry.nummer}</span>
        </label>
        <label className="flex flex-col gap-1">
          <span className="font-medium" title="Leer lassen, um ihn neu erzeugen zu lassen.">
            Tag {entry.tag_manuell ? "(von Hand)" : "(erzeugt)"}
          </span>
          <input
            aria-label="Tag"
            value={tag}
            onChange={(e) => setTagValue(e.target.value)}
            placeholder="leer: neu erzeugen"
            className="w-40 rounded-md border bg-background px-2 py-1 font-mono"
          />
        </label>
        {DIMENSIONS.map(({ key, label }) => (
          <label key={key} className="flex flex-col gap-1">
            <span className="font-medium">{label}</span>
            <input
              aria-label={label}
              list={listId(key)}
              value={values[key]}
              onChange={(e) => setValues((v) => ({ ...v, [key]: e.target.value }))}
              className="w-56 rounded-md border bg-background px-2 py-1"
            />
            <datalist id={listId(key)}>
              {offered[key].map((value) => (
                <option key={value} value={value} />
              ))}
            </datalist>
          </label>
        ))}
        <button
          type="button"
          disabled={busy || !dirty}
          onClick={() => void save()}
          className="rounded-md bg-primary px-3 py-1 font-medium text-primary-foreground disabled:opacity-50"
        >
          Speichern
        </button>
      </div>
      {error && (
        <p role="alert" className="text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
