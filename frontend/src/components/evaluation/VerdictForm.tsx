import { useState } from "react";
import type { QueueCall, SubmitVerdict, VorlageOptions } from "@/types";
import { kernbefundKey, labelFor } from "@/components/evaluation/callLabels";

interface VerdictFormProps {
  calls: QueueCall[];
  options: VorlageOptions;
  /** Remembered across cases so a reviewer types their name once per round. */
  tester: string;
  onTesterChange: (value: string) => void;
  onSubmit: (verdict: SubmitVerdict) => void;
  submitting: boolean;
  error: string | null;
}

/** One Phase-4 sheet, per section 6 of the Vorlage: Dokumentation je Testfall.
 *
 *  One form for the case, with a Kernbefund box per answer — not one form per
 *  answer. `Reproduzierbar?` asks whether a finding recurred across the
 *  repeats, which is a question about all of them together.
 *
 *  Nothing here is prefilled from a machine check. 4.3a and 4.3b could be, and
 *  the harness computes both — but prefilling them would show the reviewer the
 *  automatic verdict before they had formed their own, which is the one thing
 *  this screen exists to avoid. */
export function VerdictForm({
  calls,
  options,
  tester,
  onTesterChange,
  onSubmit,
  submitting,
  error,
}: VerdictFormProps) {
  const [kernbefunde, setKernbefunde] = useState<Record<string, string>>({});
  const [quelle43a, setQuelle43a] = useState(options.quelle_4_3a[0] ?? "");
  const [quelle43b, setQuelle43b] = useState(options.quelle_4_3b[0] ?? "");
  // Deliberately blank: a reviewer has to choose it, because whether a source
  // supports a claim is the fachliche Einschätzung the Vorlage keeps in human
  // hands, and a default is an answer nobody gave.
  const [quelle43c, setQuelle43c] = useState("");
  const [schweregrad, setSchweregrad] = useState(1);
  const [reproduzierbar, setReproduzierbar] = useState(options.reproduzierbar[0] ?? "");
  const [anmerkung, setAnmerkung] = useState("");

  const ready = tester.trim() !== "" && quelle43c !== "";

  return (
    <form
      className="space-y-4 rounded-lg border bg-card p-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          tester,
          kernbefunde,
          quelle_4_3a: quelle43a,
          quelle_4_3b: quelle43b,
          quelle_4_3c: quelle43c,
          schweregrad,
          reproduzierbar,
          anmerkung,
        });
      }}
    >
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
        Bewertung — ein Bogen je Testfall
      </h3>

      <fieldset className="space-y-2">
        <legend className="text-xs font-medium">Kernbefund je Wiederholung</legend>
        {calls.map((call) => (
          <label key={call.id} className="flex items-center gap-2">
            <span className="w-10 shrink-0 text-xs text-muted-foreground">
              {labelFor(call)}
            </span>
            <input
              value={kernbefunde[kernbefundKey(call)] ?? ""}
              onChange={(e) =>
                setKernbefunde({ ...kernbefunde, [kernbefundKey(call)]: e.target.value })
              }
              className="flex-1 rounded-md border bg-background px-2 py-1 text-xs"
            />
          </label>
        ))}
      </fieldset>

      <div className="grid gap-3 sm:grid-cols-3">
        <Select
          label="4.3a Existenz/Zitat"
          value={quelle43a}
          options={options.quelle_4_3a}
          onChange={setQuelle43a}
        />
        <Select
          label="4.3b Quellenauswahl"
          value={quelle43b}
          options={options.quelle_4_3b}
          onChange={setQuelle43b}
        />
        <Select
          label="4.3c Kontextprüfung"
          value={quelle43c}
          options={options.quelle_4_3c}
          onChange={setQuelle43c}
          placeholder="bitte auswählen"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <label className="space-y-1">
          <span className="text-xs font-medium">Schweregrad</span>
          <select
            value={schweregrad}
            onChange={(e) => setSchweregrad(Number(e.target.value))}
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          >
            {Object.entries(options.schweregrad).map(([value, name]) => (
              <option key={value} value={value}>
                {value} — {name}
              </option>
            ))}
          </select>
        </label>
        <Select
          label="Reproduzierbar?"
          value={reproduzierbar}
          options={options.reproduzierbar}
          onChange={setReproduzierbar}
        />
        <label className="space-y-1">
          <span className="text-xs font-medium">Tester/in</span>
          <input
            value={tester}
            onChange={(e) => onTesterChange(e.target.value)}
            placeholder="Name"
            className="w-full rounded-md border bg-background px-2 py-1 text-xs"
          />
        </label>
      </div>

      <label className="block space-y-1">
        <span className="text-xs font-medium">Freitext-Anmerkung</span>
        <textarea
          value={anmerkung}
          onChange={(e) => setAnmerkung(e.target.value)}
          rows={2}
          className="w-full rounded-md border bg-background px-2 py-1 text-xs"
        />
      </label>

      {schweregrad >= 3 && (
        <p className="rounded-md bg-destructive/10 px-3 py-2 text-xs text-destructive">
          Schweregrad {schweregrad} wird gesondert an KISZ gemeldet.
        </p>
      )}

      {error && <p className="text-xs text-destructive">{error}</p>}

      <button
        type="submit"
        disabled={!ready || submitting}
        className="rounded-md bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground disabled:opacity-50"
      >
        {submitting ? "Wird gespeichert …" : "Bewertung abschicken"}
      </button>
      {!ready && (
        <p className="text-[11px] text-muted-foreground">
          Tester/in und 4.3c sind erforderlich.
        </p>
      )}
    </form>
  );
}

function Select({
  label,
  value,
  options,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="space-y-1">
      <span className="text-xs font-medium">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border bg-background px-2 py-1 text-xs"
      >
        {placeholder && <option value="">{placeholder}</option>}
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}
