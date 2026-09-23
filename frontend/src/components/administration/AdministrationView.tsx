import { useCallback, useEffect, useState } from "react";
import type { CaseDraft, EvalCase, EvalRun, Session } from "@/types";
import {
  approveCase,
  createCase,
  fetchCases,
  fetchRun,
  fetchRuns,
  updateCase,
  withdrawCase,
} from "@/lib/evalApi";
import { ResultsView } from "@/components/evaluation/ResultsView";
import { RunPicker } from "@/components/evaluation/RunPicker";
import { CaseForm } from "@/components/administration/CaseForm";
import { CaseTable } from "@/components/administration/CaseTable";
import { RoundControls } from "@/components/administration/RoundControls";
import { UserPane } from "@/components/administration/UserPane";

/** Everything that changes the test set, kept away from the screen where
 *  cases are judged.
 *
 *  The separation is the point. A reviewer working a queue has no business
 *  editing the case they are judging, and the Vorlage's audit argument rests
 *  on the expected answer having been fixed before the answer was produced —
 *  "the reviewer could not have changed it" is worth being structurally true
 *  rather than merely unlikely.
 *
 *  It is a tab, not a permission. There is still no authentication anywhere in
 *  SENTRA, so this separates the two jobs; it does not restrict who does them.
 *  Saying so here because a screen labelled Administration invites the
 *  opposite assumption. */
const EMPTY: CaseDraft = {
  kategorie: "GO",
  ausgangsfrage: "",
  abteilung: "",
  erwartete_antwort: "",
  referenz_korrekt: "",
  referenz_falsch: "",
  referenz_korrekt_az: "",
  referenz_falsch_az: "",
  grund_fuer_aufnahme: "",
  grenzfall: false,
};

export function AdministrationView({ session }: { session: Session | null }) {
  const [cases, setCases] = useState<EvalCase[]>([]);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  // Whoever starts a round is usually the one who wants to see what it said,
  // and making them change tabs to find out is the kind of small friction that
  // ends with nobody looking. The same view as in Auswertung, deliberately —
  // two renderings of one round is how two people come to quote different
  // numbers from it.
  const [tab, setTab] = useState<"testfaelle" | "ergebnisse" | "benutzer">(
    "testfaelle",
  );
  const [runId, setRunId] = useState<string | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchCases()
      .then(setCases)
      .catch((e: Error) => setLoadError(e.message));
  }, []);

  useEffect(() => {
    load();
    fetchRuns()
      .then((loaded) => {
        setRuns(loaded);
        setRunId((current) => current ?? loaded[0]?.id ?? null);
      })
      .catch(() => {
        /* The case list is the point of this screen; a missing run list is not
           worth blanking it. */
      });
  }, [load]);

  const active = runs.find((r) => r.status === "laufend") ?? null;

  // Only while something is running. A round is roughly 180 calls at 20 to 29
  // seconds, and whoever started it is most likely still on this screen.
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => {
      fetchRun(active.id)
        .then((fresh) =>
          setRuns((cur) => cur.map((r) => (r.id === fresh.id ? fresh : r))),
        )
        .catch(() => {});
    }, 5000);
    return () => window.clearInterval(id);
  }, [active]);

  async function act<T>(work: () => Promise<T>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      load();
      setEditing(null);
      setCreating(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const open = cases.find((c) => c.test_id === editing) ?? null;
  const latest = open?.versions[open.versions.length - 1] ?? null;

  if (loadError) {
    return (
      <div className="mx-auto max-w-7xl p-6">
        <p className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {loadError}
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-6">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-lg font-semibold">Administration</h2>
          {tab === "ergebnisse" && (
            <RunPicker runs={runs} runId={runId} onSelect={setRunId} />
          )}
          <nav className="ml-auto flex gap-1" aria-label="Ansicht">
            {(
              [
                ["testfaelle", "Testfälle"],
                ["ergebnisse", "Ergebnisse"],
                ["benutzer", "Benutzer"],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setTab(key)}
                aria-current={tab === key ? "page" : undefined}
                className={
                  tab === key
                    ? "rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground"
                    : "rounded-md px-3 py-1 text-xs text-muted-foreground hover:bg-muted"
                }
              >
                {label}
              </button>
            ))}
          </nav>
        </div>
        <p className="text-xs text-muted-foreground">
          Testfälle anlegen, ändern, freigeben und zurückziehen — und Testrunden
          starten. Die Auswertung selbst ändert nichts daran.
        </p>
      </header>

      {tab !== "benutzer" && (
        <RoundControls
          running={active}
          onStarted={(run) => setRuns((cur) => [run, ...cur])}
          onImported={load}
        />
      )}

      {tab === "benutzer" && <UserPane session={session} />}

      {error && (
        <p className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
          {error}
        </p>
      )}

      {tab === "ergebnisse" &&
        (runId ? (
          <ResultsView key={runId} runId={runId} />
        ) : (
          <p className="text-sm text-muted-foreground">
            Noch keine Testrunde gelaufen. Oben eine starten.
          </p>
        ))}

      {tab === "testfaelle" && (
        <>
          {creating && (
            <CaseForm
              initial={EMPTY}
              categories={["GO", "GV", "AR"]}
              editingApproved={false}
              submitting={busy}
              onCancel={() => setCreating(false)}
              onSubmit={(draft) => void act(() => createCase(draft))}
            />
          )}

          {open && latest && (
            <CaseForm
              key={open.test_id}
              initial={{
                kategorie: open.kategorie,
                ausgangsfrage: latest.ausgangsfrage,
                abteilung: latest.abteilung,
                erwartete_antwort: latest.erwartete_antwort,
                referenz_korrekt: latest.referenz_korrekt,
                referenz_falsch: latest.referenz_falsch,
                referenz_korrekt_az: latest.referenz_korrekt_az,
                referenz_falsch_az: latest.referenz_falsch_az,
                grund_fuer_aufnahme: latest.grund_fuer_aufnahme,
                grenzfall: latest.grenzfall,
              }}
              categories={["GO", "GV", "AR"]}
              editingApproved={latest.status === "freigegeben"}
              submitting={busy}
              onCancel={() => setEditing(null)}
              onSubmit={(draft) => {
                // Never the category: it is baked into the Test-ID, which is
                // allocated once and never reused, so changing it would leave the
                // number saying one thing and the case another. PATCH has no
                // kategorie field for exactly that reason.
                const { kategorie, ...fields } = draft;
                void kategorie;
                void act(() => updateCase(open.test_id, fields));
              }}
            />
          )}

          <CaseTable
            cases={cases}
            busy={busy}
            onCreate={() => {
              setCreating(true);
              setEditing(null);
            }}
            onEdit={(testId) => {
              setEditing(testId);
              setCreating(false);
            }}
            onApprove={(testId) => void act(() => approveCase(testId))}
            onWithdraw={(testId) => void act(() => withdrawCase(testId))}
          />
        </>
      )}
    </div>
  );
}
