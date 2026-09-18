import type {
  Agreement,
  EvalRun,
  MachineVerdicts,
  QueueEntry,
  Sheet,
  Trend,
  TriageSummary,
  SubmitVerdict,
  Verdict,
  VorlageOptions,
} from "@/types";
import { request } from "@/lib/api";

/** The evaluation harness's API.
 *
 *  A separate process — `sentra_eval`, its own image and database — reached
 *  through the same origin because nginx routes /api/eval to it. A 502 here
 *  means the harness is not running, which is its normal state: it starts with
 *  `docker compose --profile eval up`.
 *
 *  Its own module rather than more functions in api.ts, because it talks to a
 *  different service with a different lifecycle. The shared `request` gives
 *  both the same error handling, which is worth having: both produce 503s in
 *  the same shape. */

const NOT_RUNNING = "Die Auswertung ist nicht erreichbar. Läuft der Auswertungs-Dienst?";

export function fetchRuns(): Promise<EvalRun[]> {
  return request("/eval/runs", {
    label: "Testrunden konnten nicht geladen werden",
    statusMessages: { 502: NOT_RUNNING, 503: NOT_RUNNING },
  });
}

export function fetchQueue(runId: string): Promise<QueueEntry[]> {
  return request(`/eval/runs/${runId}/queue`, {
    label: "Warteschlange konnte nicht geladen werden",
    statusMessages: { 502: NOT_RUNNING, 503: NOT_RUNNING },
  });
}

export function fetchVorlageOptions(): Promise<VorlageOptions> {
  return request("/eval/vorlage-optionen", {
    label: "Bewertungsoptionen konnten nicht geladen werden",
    statusMessages: { 502: NOT_RUNNING, 503: NOT_RUNNING },
  });
}

/** Submit one Phase-4 sheet for a case.
 *
 *  Per case, not per answer: `Reproduzierbar?` asks whether a finding recurred
 *  across the repeats, which no single answer can be asked. */
export function submitVerdict(
  runId: string,
  caseVersionId: string,
  verdict: SubmitVerdict,
): Promise<Verdict> {
  return request(`/eval/runs/${runId}/cases/${caseVersionId}/verdict`, {
    method: "POST",
    body: verdict,
    label: "Bewertung konnte nicht gespeichert werden",
    statusMessages: {
      409: "Dieser Testfall wurde in dieser Runde bereits bewertet.",
      502: NOT_RUNNING,
    },
  });
}

/** What the automated checks concluded.
 *
 *  Called **after** a sheet is submitted and never before. The queue carries
 *  no machine verdicts at all, so this is the only way to see them — which is
 *  the point. Section 6 of the Vorlage makes the disagreement between the
 *  automatic verdict and the human one the headline measurement; showing the
 *  machine's answer first would turn it into a measure of anchoring. */
export function fetchMachineVerdicts(callId: string): Promise<MachineVerdicts> {
  return request(`/eval/calls/${callId}/machine-verdicts`, {
    label: "Automatikprüfung konnte nicht geladen werden",
    statusMessages: { 502: NOT_RUNNING },
  });
}


// ── What the round concluded ────────────────────────────────────────
//
// None of these are ordered before a sheet is submitted, unlike
// fetchMachineVerdicts above: they are about the round rather than about the
// case in front of the reviewer, and a reviewer working the queue does not see
// this screen.

export function fetchTriage(runId: string): Promise<TriageSummary> {
  return request(`/eval/runs/${runId}/triage`, {
    label: "Triage konnte nicht geladen werden",
    statusMessages: { 502: NOT_RUNNING, 503: NOT_RUNNING },
  });
}

/** Stufe 1 against a human. Section 6 calls this the most important number in
 *  the process, and it is the one that calibrates the Prüfschwelle. */
export function fetchAgreement(runId: string): Promise<Agreement> {
  return request(`/eval/runs/${runId}/abweichung`, {
    label: "Abweichungsquote konnte nicht geladen werden",
    statusMessages: { 502: NOT_RUNNING, 503: NOT_RUNNING },
  });
}

export function fetchSheets(runId: string): Promise<Sheet[]> {
  return request(`/eval/runs/${runId}/boegen`, {
    label: "Dokumentationsbögen konnten nicht geladen werden",
    statusMessages: { 502: NOT_RUNNING, 503: NOT_RUNNING },
  });
}

/** Schweregrad 3 and 4, which leave the WD process and go to KISZ. */
export function fetchKisz(runId: string): Promise<Verdict[]> {
  return request(`/eval/runs/${runId}/kisz`, {
    label: "KISZ-Meldungen konnten nicht geladen werden",
    statusMessages: { 502: NOT_RUNNING, 503: NOT_RUNNING },
  });
}

export function fetchTrend(): Promise<Trend> {
  return request("/eval/trend", {
    label: "Trendauswertung konnte nicht geladen werden",
    statusMessages: { 502: NOT_RUNNING, 503: NOT_RUNNING },
  });
}
