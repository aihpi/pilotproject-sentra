import type { AppConfig, DocumentInfo, DocumentResult, ExternalSourceResult, FeedbackRequest, GeneratedAnswerResult, IngestionStatus, UploadResponse, VolumeFile, WithdrawResult } from "@/types";

export const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

/** Where to fetch a document, optionally opening it at a page.
 *
 *  `#page=` is the PDF open-parameter every browser viewer understands, and it
 *  is a fragment — never sent to the server, so it cannot affect what is
 *  served or be logged. Omitted for page 0, which is what a chunk indexed
 *  before #134 carries: a viewer told to open at page 0 lands wherever it
 *  likes, which is worse than not being told. */
export function pdfUrl(sourceFile: string, page = 0): string {
  const url = `${API_BASE}/documents/${encodeURIComponent(sourceFile)}`;
  return page > 0 ? `${url}#page=${page}` : url;
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
  /** PATCH is here for the case store, where changing a case is deliberately
   *  not a full replacement: omitted fields are carried over, and the harness
   *  decides whether that edits the draft or adds a version. */
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  /** Sent as JSON. Its presence is what adds the Content-Type header. */
  body?: unknown;
  /** Sent as-is, for an endpoint that takes bytes rather than JSON — the
   *  collection-sheet upload, which posts the File straight through. Here
   *  rather than as its own fetch so that everything below, especially the
   *  server's own reason for refusing, is shared: an upload refused because
   *  row 4 has no expected answer must say that, not "(HTTP 422)". */
  /** A body the browser serialises itself: a Blob for bytes, FormData for
   *  a file upload. Never given a Content-Type here — for FormData only the
   *  browser knows the multipart boundary, and setting the header by hand
   *  omits it and produces a request the server cannot parse. */
  raw?: Blob | FormData;
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
export async function request<T>(
  path: string,
  options: RequestOptions,
): Promise<T> {
  const { label, method = "GET", body, raw, statusMessages } = options;

  let response: Response;
  try {
    // Headers built once rather than spread twice. Two `headers:` keys in one
    // object literal is not a merge — the later one replaces the earlier.
    const headers: Record<string, string> = {};
    // No Content-Type for the raw case: the browser sets it from the Blob or
    // the FormData, and it is the only thing that can — see RequestOptions.
    if (raw === undefined && body !== undefined)
      headers["Content-Type"] = "application/json";

    response = await fetch(`${API_BASE}${path}`, {
      method,
      // The session cookie. Under compose nginx proxies /api, so the browser
      // sees one origin and the default would have sent it anyway — but the
      // vite dev server calls cross-origin, where the default is not to, and
      // the difference would show up as "the login works in production and
      // silently does not in development".
      credentials: "include",
      ...(Object.keys(headers).length > 0 ? { headers } : {}),
      ...(raw !== undefined
        ? { body: raw }
        : body === undefined
          ? {}
          : { body: JSON.stringify(body) }),
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
  // 204 has no body. Parsing one would throw on exactly the calls that
  // succeeded — deleting a user, signing out.
  if (response.status === 204) return undefined as T;
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
  return request("/config", {
    label: "Konfiguration konnte nicht geladen werden",
  });
}

export function fetchDocuments(): Promise<DocumentInfo[]> {
  return request("/documents", {
    label: "Dokumente konnten nicht geladen werden",
  });
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
  return request("/ingest/status", {
    label: "Status konnte nicht abgerufen werden",
  });
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
  const data = await request<{ documents: DocumentResult[] }>(
    "/explorer/documents",
    {
      method: "POST",
      body: explorerBody(query, dateRange, filters, { top_k: topK }),
      label: "Dokumentsuche fehlgeschlagen",
    },
  );
  return data.documents;
}

/** UC#4: Find similar documents */
export async function findSimilarDocuments(
  aktenzeichen: string,
  topK: number = 10,
): Promise<DocumentResult[]> {
  const data = await request<{ documents: DocumentResult[] }>(
    "/explorer/similar",
    {
      method: "POST",
      body: { aktenzeichen, top_k: topK },
      label: "Ähnliche Dokumente fehlgeschlagen",
    },
  );
  return data.documents;
}

/** UC#6: Find external sources */
export async function findExternalSources(
  query: string,
  dateRange?: DateRange,
  filters?: ExplorerFilters,
): Promise<ExternalSourceResult[]> {
  const data = await request<{ sources: ExternalSourceResult[] }>(
    "/explorer/sources",
    {
      method: "POST",
      body: explorerBody(query, dateRange, filters),
      label: "Quellensuche fehlgeschlagen",
    },
  );
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

/** Add documents to the corpus. Admin only; the backend enforces it.
 *
 *  Sent as FormData through `raw`, so no Content-Type is set here — the
 *  browser has to write it itself, because only it knows the multipart
 *  boundary. Setting `multipart/form-data` by hand omits the boundary and the
 *  request arrives unparseable.
 *
 *  A 200 does not mean every file was taken. The response reports per file,
 *  because one bad name in a dragged-in folder should not discard the rest. */
export async function uploadDocuments(files: File[]): Promise<UploadResponse> {
  const form = new FormData();
  for (const file of files) form.append("files", file);

  return request<UploadResponse>("/documents", {
    method: "POST",
    raw: form,
    label: "Der Upload ist fehlgeschlagen",
    statusMessages: {
      401: "Zum Hochladen ist eine Anmeldung als Administrator nötig.",
      403: "Zum Hochladen wird die Rolle „admin“ benötigt.",
      413: "Die Dateien sind zu groß.",
    },
  });
}

/** What is on the volume, as opposed to what is indexed. Admin only. */
export function fetchVolumeFiles(): Promise<VolumeFile[]> {
  return request<VolumeFile[]>("/documents/files", {
    label: "Die Dateien auf dem Volume konnten nicht gelesen werden",
  });
}

/** Take a document out of the index, keeping the file and the registry row.
 *
 *  Withdrawal, not deletion. Admin only; the backend enforces it. */
export function withdrawDocument(sourceFile: string): Promise<WithdrawResult> {
  return request<WithdrawResult>(
    `/documents/${encodeURIComponent(sourceFile)}/withdraw`,
    {
      method: "POST",
      label: "Das Dokument konnte nicht zurückgezogen werden",
      statusMessages: {
        401: "Zum Zurückziehen ist eine Anmeldung als Administrator nötig.",
        403: "Zum Zurückziehen wird die Rolle „admin“ benötigt.",
      },
    },
  );
}
