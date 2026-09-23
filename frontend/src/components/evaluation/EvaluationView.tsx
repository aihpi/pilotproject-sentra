import { useCallback, useEffect, useState } from "react";
import type {
  EvalRun,
  MachineVerdicts,
  QueueEntry,
  SourceRef,
  SubmitVerdict,
  VorlageOptions,
  Session,
} from "@/types";
import {
  fetchMachineVerdicts,
  fetchQueue,
  fetchRun,
  fetchRuns,
  fetchVorlageOptions,
  submitVerdict,
} from "@/lib/evalApi";
import { AnswerPane } from "@/components/evaluation/AnswerPane";
import { CasePane } from "@/components/evaluation/CasePane";
import { MachineVerdictPane } from "@/components/evaluation/MachineVerdictPane";
import { PdfPane } from "@/components/evaluation/PdfPane";
import { QueueList } from "@/components/evaluation/QueueList";
import { ResultsView } from "@/components/evaluation/ResultsView";
import { RunPicker } from "@/components/evaluation/RunPicker";
import { VerdictForm } from "@/components/evaluation/VerdictForm";

/** Stufe 2: working a round's queue.
 *
 *  The order of operations here is the point of the screen. A reviewer reads
 *  the answer beside the case, writes their assessment, submits it, and only
 *  then sees what the automated checks said. Section 6 of the Vorlage makes
 *  the disagreement between those two the most important number in the
 *  process; it measures nothing if the human saw the machine's answer first.
 *
 *  The harness enforces it on its side — the queue carries no machine verdicts
 *  at all — so the only way this screen could break it is by fetching them
 *  early. That fetch lives in the submit handler and nowhere else. */
export function EvaluationView({ session }: { session: Session | null }) {
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [queue, setQueue] = useState<QueueEntry[]>([]);
  const [options, setOptions] = useState<VorlageOptions | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [activeCall, setActiveCall] = useState(0);
  const [verdicts, setVerdicts] = useState<MachineVerdicts | null>(null);
  // The document open for 4.3c. Cleared with the case, because a passage from
  // the previous case beside this one's answer is worse than no passage.
  const [openSource, setOpenSource] = useState<SourceRef | null>(null);
  // Reviewing and reading results are different jobs, and the second must not
  // be reachable by scrolling past the first: a reviewer who sees the round's
  // verdicts while working the queue is anchored by them, which is the thing
  // the whole screen is arranged to prevent.
  const [tab, setTab] = useState<"pruefen" | "ergebnisse">("pruefen");
  const [tester, setTester] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchRuns(), fetchVorlageOptions()])
      .then(([loadedRuns, loadedOptions]) => {
        setRuns(loadedRuns);
        setOptions(loadedOptions);
        setRunId((current) => current ?? loadedRuns[0]?.id ?? null);
      })
      .catch((e: Error) => setLoadError(e.message));
  }, []);

  const loadQueue = useCallback((id: string) => {
    fetchQueue(id)
      .then((entries) => {
        setQueue(entries);
        setSelected((current) =>
          current && entries.some((e) => e.case_version_id === current)
            ? current
            : (entries.find((e) => !e.assessed)?.case_version_id ?? null),
        );
      })
      .catch((e: Error) => setLoadError(e.message));
  }, []);

  useEffect(() => {
    if (runId) loadQueue(runId);
  }, [runId, loadQueue]);

  // A round is roughly 180 calls at 20 to 29 seconds each, so the screen has
  // to move on its own or it is indistinguishable from one that has hung —
  // and somebody will restart the stack mid-round. Polling stops the moment
  // the round is no longer running, and the queue is reloaded once, because
  // that is when there is finally something to review.
  const active =
    runs.find((r) => r.id === runId && r.status === "laufend") ?? null;

  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => {
      fetchRun(active.id)
        .then((fresh) => {
          setRuns((current) =>
            current.map((r) => (r.id === fresh.id ? fresh : r)),
          );
          if (fresh.status !== "laufend") loadQueue(fresh.id);
        })
        .catch(() => {
          /* A poll that fails is not worth a message; the next one may not. */
        });
    }, 5000);
    return () => window.clearInterval(id);
  }, [active, loadQueue]);

  const entry = queue.find((e) => e.case_version_id === selected) ?? null;

  // A different case means a different assessment, so anything revealed about
  // the last one has to go. Leaving it would show one case's machine verdict
  // while the next one is still being read.
  function selectCase(caseVersionId: string) {
    setSelected(caseVersionId);
    setActiveCall(0);
    setVerdicts(null);
    setOpenSource(null);
    setError(null);
  }

  async function submit(verdict: SubmitVerdict) {
    if (!runId || !entry) return;
    setSubmitting(true);
    setError(null);
    try {
      await submitVerdict(runId, entry.case_version_id, verdict);
      // Only now. See the component docstring.
      const call = entry.calls[activeCall];
      if (call) setVerdicts(await fetchMachineVerdicts(call.id));
      loadQueue(runId);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  if (loadError) {
    return (
      <div className="mx-auto max-w-2xl p-6">
        <p className="rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm text-destructive">
          {loadError}
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-4 p-6">
      <header className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold">Auswertung</h2>
        <RunPicker runs={runs} runId={runId} onSelect={setRunId} />

        <nav className="ml-auto flex gap-1" aria-label="Ansicht">
          {(
            [
              ["pruefen", "Prüfen"],
              ["ergebnisse", "Ergebnisse"],
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
      </header>

      {tab === "ergebnisse" &&
        (runId ? (
          <ResultsView key={runId} runId={runId} />
        ) : (
          <p className="text-sm text-muted-foreground">
            Keine Testrunde ausgewählt.
          </p>
        ))}

      {tab === "pruefen" && (
        <>
          <div className="grid gap-4 lg:grid-cols-[minmax(12rem,1fr)_minmax(0,2.4fr)_minmax(14rem,1.2fr)]">
            <QueueList
              entries={queue}
              selected={selected}
              onSelect={selectCase}
            />

            {entry ? (
              <div className="space-y-4">
                <AnswerPane
                  calls={entry.calls}
                  activeIndex={activeCall}
                  onSelectCall={setActiveCall}
                  onSelectSource={setOpenSource}
                  selectedSource={openSource?.aktenzeichen}
                />
                {openSource && (
                  <PdfPane
                    source={openSource}
                    onClose={() => setOpenSource(null)}
                  />
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Keinen Testfall ausgewählt.
              </p>
            )}

            {entry && <CasePane entry={entry} />}
          </div>

          {entry && options && (
            <>
              <VerdictForm
                key={entry.case_version_id}
                calls={entry.calls}
                options={options}
                tester={tester}
                angemeldetAls={session?.benutzername ?? null}
                onTesterChange={setTester}
                onSubmit={submit}
                submitting={submitting}
                error={error}
              />
              <MachineVerdictPane verdicts={verdicts} />
            </>
          )}
        </>
      )}
    </div>
  );
}
