import type {
  AppConfig,
  DocumentInfo,
  FeedbackRequest,
  DocumentResult,
  GeneratedAnswerResult,
  ExternalSourceResult,
  IngestionStatus,
} from "@/types";

export const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

export function pdfUrl(sourceFile: string): string {
  return `${API_BASE}/documents/${encodeURIComponent(sourceFile)}`;
}

export function formatDate(dateStr: string): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  return d.toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

// ── The one request path ────────────────────────────────────────────

interface RequestOptions {
  /** Fallback shown to the user when the server said nothing more useful. */
  label: string;
  method?: "GET" | "POST";
  /** Sent as JSON. Its presence is what adds the Content-Type header. */
  body?: unknown;
  /** Statuses this client understands better than the server does, so its
   *  wording wins. Only the ingest 409 so far. */
  statusMessages?: Record<number, string>;
}

/** Every endpoint answers with a JSON body, including the ones whose body
 *  the caller ignores, so this always parses one. A future 204 would need
 *  handling here rather than at the call site.
 *
 *  Exported so `evalApi.ts` uses it too. The evaluation harness is a separate
 *  process, but nginx routes /api/eval to it, so from the browser it is the
 *  same origin and the same error handling — including the 503 wording, which
 *  both services produce in the same shape. */
export async function request<T>(path: string, options: RequestOptions): Promise<T> {
  const { label, method = "GET", body, statusMessages } = options;

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      ...(body === undefined
        ? {}
        : {
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }),
    });
  } catch {
    // fetch only rejects when the request never completed at all: offline,
    // DNS, connection refused. The browser's own message for that is English
    // and technical ("Failed to fetch"), so it is not passed on.
    throw new Error(`${label} (keine Verbindung zum Server)`);
  }

  if (!response.ok) {
    throw new Error(await failureMessage(response, label, statusMessages));
  }
  return response.json();
}

/** What to tell the user about a response that was not ok.
 *
 * Most specific first. The client's own wording wins where it has some,
 * because it knows things the server does not: the ingest 409 means "a run is
 * already going" rather than any generic conflict. Otherwise the server's
 * reason is used, which is the point of this: the backend distinguishes a
 * dependency being down from a query finding nothing, and saying only
 * "(HTTP 503)" throws that away and invites the user to retype a query that
 * was never the problem.
 */
async function failureMessage(
  response: Response,
  label: string,
  statusMessages?: Record<number, string>,
): Promise<string> {
  const known = statusMessages?.[response.status];
  if (known) return known;

  const detail = await serverDetail(response);
  if (detail) return detail;

  return `${label} (HTTP ${response.status})`;
}

/** The reason the API gave, if it gave one a person can read.
 *
 * FastAPI puts it in `detail`. Two cases where that is not usable text: a
 * validation error puts an array of objects there, which is for whoever wrote
 * the request and would render as "[object Object]"; and the body may not be
 * JSON at all, since a 503 from nginx rather than from the app is an HTML
 * page. Both fall through to the label.
 */
async function serverDetail(response: Response): Promise<string | null> {
  try {
    const body = await response.json();
    const detail = (body as { detail?: unknown } | null)?.detail;
    return typeof detail === "string" && detail.trim() ? detail : null;
  } catch {
    return null;
  }
}

// ── Document management ─────────────────────────────────────────────

export function fetchConfig(): Promise<AppConfig> {
  return request("/config", { label: "Konfiguration konnte nicht geladen werden" });
}

export function fetchDocuments(): Promise<DocumentInfo[]> {
  return request("/documents", { label: "Dokumente konnten nicht geladen werden" });
}

export function startIngestion(force = false): Promise<{ status: string }> {
  return request(force ? "/ingest?force=true" : "/ingest", {
    method: "POST",
    label: "Ingestion fehlgeschlagen",
    // The server says 409 when a run is already going. That is not a failure
    // the user needs a status code for.
    statusMessages: { 409: "Ingestion läuft bereits" },
  });
}

export function getIngestionStatus(): Promise<IngestionStatus> {
  return request("/ingest/status", { label: "Status konnte nicht abgerufen werden" });
}

// ── Feedback ────────────────────────────────────────────────────────

export async function submitFeedback(feedback: FeedbackRequest): Promise<void> {
  await request("/feedback", {
    method: "POST",
    body: feedback,
    label: "Feedback fehlgeschlagen",
  });
}

// ── Explorer API (v2) ──────────────────────────────────────────────

interface DateRange {
  date_from?: string | null;
  date_to?: string | null;
}

interface ExplorerFilters {
  fachbereich?: string | null;
  document_type?: string | null;
}

/** The query-plus-filters shape the four search endpoints share. `||` rather
 *  than `??` so an empty filter string keeps reaching the server as null. */
function explorerBody(
  query: string,
  dateRange?: DateRange,
  filters?: ExplorerFilters,
  extra?: Record<string, unknown>,
) {
  return {
    query,
    date_range: dateRange || null,
    fachbereich: filters?.fachbereich || null,
    document_type: filters?.document_type || null,
    ...extra,
  };
}

/** UC#1: Find documents by topic */
export async function searchDocumentsByTopic(
  query: string,
  dateRange?: DateRange,
  topK: number = 20,
  filters?: ExplorerFilters,
): Promise<DocumentResult[]> {
  const data = await request<{ documents: DocumentResult[] }>("/explorer/documents", {
    method: "POST",
    body: explorerBody(query, dateRange, filters, { top_k: topK }),
    label: "Dokumentsuche fehlgeschlagen",
  });
  return data.documents;
}

/** UC#4: Find similar documents */
export async function findSimilarDocuments(
  aktenzeichen: string,
  topK: number = 10,
): Promise<DocumentResult[]> {
  const data = await request<{ documents: DocumentResult[] }>("/explorer/similar", {
    method: "POST",
    body: { aktenzeichen, top_k: topK },
    label: "Ähnliche Dokumente fehlgeschlagen",
  });
  return data.documents;
}

/** UC#6: Find external sources */
export async function findExternalSources(
  query: string,
  dateRange?: DateRange,
  filters?: ExplorerFilters,
): Promise<ExternalSourceResult[]> {
  const data = await request<{ sources: ExternalSourceResult[] }>("/explorer/sources", {
    method: "POST",
    body: explorerBody(query, dateRange, filters),
    label: "Quellensuche fehlgeschlagen",
  });
  return data.sources;
}

/** UC#10: Answer a Fachfrage */
export function answerQuestion(
  query: string,
  dateRange?: DateRange,
  topK: number = 10,
  filters?: ExplorerFilters,
  systemPrompt?: string | null,
): Promise<GeneratedAnswerResult> {
  return request("/explorer/answer", {
    method: "POST",
    body: explorerBody(query, dateRange, filters, {
      top_k: topK,
      system_prompt: systemPrompt || null,
    }),
    label: "Fachfrage fehlgeschlagen",
  });
}

/** UC#2: Generate topic overview */
export function generateOverview(
  query: string,
  dateRange?: DateRange,
  topK: number = 10,
  filters?: ExplorerFilters,
  systemPrompt?: string | null,
): Promise<GeneratedAnswerResult> {
  return request("/explorer/overview", {
    method: "POST",
    body: explorerBody(query, dateRange, filters, {
      top_k: topK,
      system_prompt: systemPrompt || null,
    }),
    label: "Themenüberblick fehlgeschlagen",
  });
}
