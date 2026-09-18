import type { EvalRun } from "@/types";

/** Choosing which round is on screen.
 *
 *  Shared by Auswertung and Administration rather than written twice: both
 *  show a round's results, and a picker that listed rounds differently in the
 *  two places would be a small but genuine way to look at one round while
 *  believing you are looking at another.
 *
 *  The audit warning travels with it for the same reason. A round where a case
 *  was approved after the round started proves nothing — the expectation could
 *  have been written to fit the answer — and that fact has to reach whoever is
 *  reading the round, on whichever screen they are reading it. */
export function RunPicker({
  runs,
  runId,
  onSelect,
}: {
  runs: EvalRun[];
  runId: string | null;
  onSelect: (id: string) => void;
}) {
  const run = runs.find((r) => r.id === runId) ?? null;

  return (
    <>
      <select
        value={runId ?? ""}
        onChange={(e) => onSelect(e.target.value)}
        aria-label="Testrunde"
        className="rounded-md border bg-background px-2 py-1 text-xs"
      >
        {runs.map((r) => (
          <option key={r.id} value={r.id}>
            {r.label || r.id.slice(0, 8)} — {r.status}
          </option>
        ))}
      </select>

      {run && !run.audit_ok && (
        <span
          className="rounded-md bg-destructive/10 px-2 py-1 text-xs text-destructive"
          title="Mindestens ein Testfall wurde erst nach dem Start der Runde freigegeben."
        >
          Prüfkette nicht belastbar
        </span>
      )}

      {runs.length === 0 && (
        <span className="text-xs text-muted-foreground">Keine Testrunden vorhanden.</span>
      )}
    </>
  );
}
