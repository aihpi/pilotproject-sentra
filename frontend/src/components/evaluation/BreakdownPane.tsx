import { useEffect, useState } from "react";
import type { BreakdownRow } from "@/types";
import { fetchBreakdown } from "@/lib/evalApi";

const DIMENSIONEN = [
  { key: "testart", label: "Testart" },
  { key: "kategorie", label: "Bereich" },
  { key: "frageform", label: "Frageform" },
  { key: "herkunft", label: "Herkunft" },
] as const;

function percent(part: number, whole: number): string {
  return whole === 0 ? "—" : `${Math.round((part / whole) * 100)} %`;
}

/** Results broken down by the cases' labels (#289).
 *
 *  One label, or two combined, for this round or every round. What it is for
 *  is the question one category could not answer: does SENTRA fail on precise
 *  questions, or in WD 4, or only on precise questions in WD 4.
 *
 *  By the labels as they are now: correcting a label re-sorts past rounds. */
export function BreakdownPane({ runId }: { runId: string }) {
  const [first, setFirst] = useState("testart");
  const [second, setSecond] = useState("");
  const [allRounds, setAllRounds] = useState(false);
  const [rows, setRows] = useState<BreakdownRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const dimensionen = second && second !== first ? [first, second] : [first];

  useEffect(() => {
    let current = true;
    fetchBreakdown(dimensionen, allRounds ? undefined : runId)
      .then((loaded) => current && (setRows(loaded), setError(null)))
      .catch((e: Error) => current && setError(e.message));
    return () => {
      current = false;
    };
    // dimensionen is derived from first and second.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [first, second, allRounds, runId]);

  const label = (key: string) => DIMENSIONEN.find((d) => d.key === key)?.label ?? key;

  return (
    <section className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <h3 className="mr-2 font-semibold uppercase tracking-wider text-muted-foreground">
          Aufschlüsselung
        </h3>
        <select
          aria-label="Aufschlüsseln nach"
          value={first}
          onChange={(e) => setFirst(e.target.value)}
          className="rounded-md border bg-background px-2 py-1"
        >
          {DIMENSIONEN.map((d) => (
            <option key={d.key} value={d.key}>
              nach {d.label}
            </option>
          ))}
        </select>
        <select
          aria-label="Und nach"
          value={second}
          onChange={(e) => setSecond(e.target.value)}
          className="rounded-md border bg-background px-2 py-1"
        >
          <option value="">und nichts weiter</option>
          {DIMENSIONEN.filter((d) => d.key !== first).map((d) => (
            <option key={d.key} value={d.key}>
              und nach {d.label}
            </option>
          ))}
        </select>
        <label className="ml-2 flex items-center gap-1">
          <input
            type="checkbox"
            checked={allRounds}
            onChange={(e) => setAllRounds(e.target.checked)}
          />
          alle Runden
        </label>
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}

      {rows && rows.length === 0 && (
        <p className="text-xs text-muted-foreground">Noch keine Ergebnisse.</p>
      )}

      {rows && rows.length > 0 && (
        <table className="w-full text-xs">
          <thead className="text-left text-muted-foreground">
            <tr>
              {dimensionen.map((d) => (
                <th key={d} className="py-1 pr-3 font-medium">
                  {label(d)}
                </th>
              ))}
              <th className="py-1 pr-3 font-medium">Fälle</th>
              <th className="py-1 pr-3 font-medium" title="Mindestens ein automatischer Befund">
                auffällig
              </th>
              <th
                className="py-1 pr-3 font-medium"
                title="Wie oft Automatik und manuelle Prüfung bei 4.3b nicht übereinstimmen"
              >
                Abweichung
              </th>
              <th className="py-1 font-medium">Befunde</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={dimensionen.map((d) => row.werte[d]).join("|")} className="border-t">
                {dimensionen.map((d) => (
                  <td key={d} className="py-1 pr-3">
                    {row.werte[d]}
                  </td>
                ))}
                <td className="py-1 pr-3 tabular-nums">{row.faelle}</td>
                <td className="py-1 pr-3 tabular-nums">
                  {row.auffaellig} ({percent(row.auffaellig, row.faelle)})
                </td>
                <td className="py-1 pr-3 tabular-nums">
                  {row.abweichung.abweichungsquote === null
                    ? "nicht bewertet"
                    : `${Math.round(row.abweichung.abweichungsquote * 100)} %`}
                </td>
                <td className="py-1 text-muted-foreground">
                  {Object.entries(row.befunde)
                    .sort(([, a], [, b]) => b - a)
                    .map(([pruefung, n]) => `${pruefung} ${n}`)
                    .join(", ") || "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
