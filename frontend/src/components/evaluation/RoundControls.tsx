import { useRef, useState } from "react";
import type { EvalRun, ImportReport } from "@/types";
import { importSheet, startRun } from "@/lib/evalApi";
import { Badge } from "@/components/ui/badge";

/** Getting a round going, without a terminal.
 *
 *  Both of these were `docker compose exec` commands, which made whoever has a
 *  checkout the bottleneck for every round WD wants. Reviewing already worked
 *  in the browser; nothing before it did.
 *
 *  Deliberately plain, and deliberately at the top of the tab rather than
 *  behind a dialog: these are the two things somebody arriving to run a round
 *  came here to do, and a round takes an hour, so the moment of starting one
 *  is not a moment to be guessing where the button is. */
export function RoundControls({
  running,
  onStarted,
  onImported,
}: {
  /** The round currently in flight, if any. Starting a second is refused by
   *  the harness, so the button says so rather than letting somebody find out
   *  from a 409. */
  running: EvalRun | null;
  onStarted: (run: EvalRun) => void;
  onImported: () => void;
}) {
  const [label, setLabel] = useState("");
  const [repeats, setRepeats] = useState(3);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      onStarted(await startRun(label.trim(), repeats));
      setLabel("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    setReport(null);
    try {
      setReport(await importSheet(file));
      onImported();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      // So the same file can be chosen again after a correction. Without this
      // the input holds the old selection and nothing happens on re-pick.
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  return (
    <section className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium">Bezeichnung der Runde</span>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="z. B. Runde September"
            className="w-56 rounded-md border bg-background px-2 py-1 text-xs"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs">
          <span className="font-medium" title="4.1 Wiederholungslauf verlangt drei.">
            Wiederholungen
          </span>
          <input
            type="number"
            min={1}
            max={10}
            value={repeats}
            onChange={(e) => setRepeats(Number(e.target.value))}
            className="w-20 rounded-md border bg-background px-2 py-1 text-xs"
          />
        </label>

        <button
          type="button"
          onClick={start}
          disabled={busy || running !== null}
          className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
        >
          {running ? "Eine Runde läuft bereits" : "Testrunde starten"}
        </button>

        <div className="ml-auto flex flex-col gap-1 text-xs">
          <span className="font-medium">Testfälle aus Erfassungsvorlage</span>
          <input
            ref={fileInput}
            type="file"
            accept=".xlsx"
            aria-label="Erfassungsvorlage hochladen"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void upload(file);
            }}
            className="text-xs file:mr-2 file:rounded-md file:border file:bg-background file:px-2 file:py-1 file:text-xs"
          />
        </div>
      </div>

      {running && <Progress run={running} />}

      {report && <ImportSummary report={report} />}

      {error && (
        <p className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
          {error}
        </p>
      )}

      <p className="text-xs text-muted-foreground">
        Hochgeladene Testfälle sind immer Entwürfe. Über die Freigabe entscheidet die fachliche
        Durchsicht — ein Upload kann nicht ändern, wogegen eine Runde misst.
      </p>
    </section>
  );
}

/** How far along a round is.
 *
 *  A round is roughly 180 calls at 20 to 29 seconds each, so without this the
 *  screen is indistinguishable from one that has hung — and somebody will
 *  start a second round, or restart the stack mid-round. */
function Progress({ run }: { run: EvalRun }) {
  const done = run.done ?? 0;
  const total = run.total ?? 0;
  const percent = total > 0 ? Math.round((done / total) * 100) : 0;

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 text-xs">
        <Badge variant="secondary">{run.status}</Badge>
        <span className="tabular-nums text-muted-foreground">
          {done} von {total} Aufrufen
        </span>
        {(run.failed ?? 0) > 0 && (
          <Badge variant="destructive">{run.failed} fehlgeschlagen</Badge>
        )}
      </div>
      <div
        className="h-1.5 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Fortschritt der Testrunde"
      >
        <div className="h-full bg-primary transition-all" style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

/** What the upload did, by Test-ID.
 *
 *  Counts alone leave the author wondering which rows landed, and the IDs are
 *  what they will look for next. */
function ImportSummary({ report }: { report: ImportReport }) {
  const lines: [string, string[]][] = [
    ["angelegt", report.angelegt],
    ["aktualisiert", report.aktualisiert],
    ["unverändert", report.unveraendert],
  ];

  return (
    <div className="rounded-md bg-muted/40 p-2 text-xs">
      {lines
        .filter(([, ids]) => ids.length > 0)
        .map(([was, ids]) => (
          <p key={was}>
            <span className="font-medium">
              {ids.length} {was}:{" "}
            </span>
            <span className="text-muted-foreground">{ids.join(", ")}</span>
          </p>
        ))}
      {lines.every(([, ids]) => ids.length === 0) && (
        <p className="text-muted-foreground">Die Datei enthielt keine Testfälle.</p>
      )}
    </div>
  );
}
