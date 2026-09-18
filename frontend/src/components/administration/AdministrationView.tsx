import { useCallback, useEffect, useState } from "react";
import type { CaseDraft, EvalCase, EvalRun } from "@/types";
import {
  approveCase,
  createCase,
  fetchCases,
  fetchRun,
  fetchRuns,
  updateCase,
  withdrawCase,
} from "@/lib/evalApi";
import { CaseForm } from "@/components/administration/CaseForm";
import { CaseTable } from "@/components/administration/CaseTable";
import { RoundControls } from "@/components/administration/RoundControls";

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

export function AdministrationView() {
  const [cases, setCases] = useState<EvalCase[]>([]);
  const [runs, setRuns] = useState<EvalRun[]>([]);
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
      .then(setRuns)
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
      <header>
        <h2 className="text-lg font-semibold">Administration</h2>
        <p className="text-xs text-muted-foreground">
          Testfälle anlegen, ändern, freigeben und zurückziehen — und Testrunden
          starten. Die Auswertung selbst ändert nichts daran.
        </p>
      </header>

      <RoundControls
        running={active}
        onStarted={(run) => setRuns((cur) => [run, ...cur])}
        onImported={load}
      />

      {error && (
        <p className="rounded-md border border-destructive/40 bg-destructive/5 p-2 text-xs text-destructive">
          {error}
        </p>
      )}

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
    </div>
  );
}
