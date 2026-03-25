import type {
  DocumentInfo,
  FeedbackRequest,
  HealthResponse,
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

// ── Document management ─────────────────────────────────────────────

export async function fetchDocuments(): Promise<DocumentInfo[]> {
  const response = await fetch(`${API_BASE}/documents`);
  if (!response.ok) {
    throw new Error(`Dokumente konnten nicht geladen werden (HTTP ${response.status})`);
  }
  return response.json();
}

export async function startIngestion(force = false): Promise<{ status: string }> {
  const url = force ? `${API_BASE}/ingest?force=true` : `${API_BASE}/ingest`;
  const response = await fetch(url, { method: "POST" });
  if (response.status === 409) {
    throw new Error("Ingestion läuft bereits");
  }
  if (!response.ok) {
    throw new Error(`Ingestion fehlgeschlagen (HTTP ${response.status})`);
  }
  return response.json();
}

export async function getIngestionStatus(): Promise<IngestionStatus> {
  const response = await fetch(`${API_BASE}/ingest/status`);
  if (!response.ok) {
    throw new Error(`Status konnte nicht abgerufen werden (HTTP ${response.status})`);
  }
  return response.json();
}

// ── Feedback ────────────────────────────────────────────────────────

export async function submitFeedback(feedback: FeedbackRequest): Promise<void> {
  const response = await fetch(`${API_BASE}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(feedback),
  });
  if (!response.ok) {
    throw new Error(`Feedback fehlgeschlagen (HTTP ${response.status})`);
  }
}

// ── Health ──────────────────────────────────────────────────────────

export async function checkHealth(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE}/health`);
  if (!response.ok) {
    throw new Error(`Health-Check fehlgeschlagen (HTTP ${response.status})`);
  }
  return response.json();
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

/** UC#1: Find documents by topic */
export async function searchDocumentsByTopic(
  query: string,
  dateRange?: DateRange,
  topK: number = 20,
  filters?: ExplorerFilters,
): Promise<DocumentResult[]> {
  const response = await fetch(`${API_BASE}/explorer/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      date_range: dateRange || null,
      top_k: topK,
      fachbereich: filters?.fachbereich || null,
      document_type: filters?.document_type || null,
    }),
  });
  if (!response.ok) {
    throw new Error(`Dokumentsuche fehlgeschlagen (HTTP ${response.status})`);
  }
  const data = await response.json();
  return data.documents;
}

/** UC#4: Find similar documents */
export async function findSimilarDocuments(
  aktenzeichen: string,
  topK: number = 10,
): Promise<DocumentResult[]> {
  const response = await fetch(`${API_BASE}/explorer/similar`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ aktenzeichen, top_k: topK }),
  });
  if (!response.ok) {
    throw new Error(`Ähnliche Dokumente fehlgeschlagen (HTTP ${response.status})`);
  }
  const data = await response.json();
  return data.documents;
}

/** UC#6: Find external sources */
export async function findExternalSources(
  query: string,
  dateRange?: DateRange,
  filters?: ExplorerFilters,
): Promise<ExternalSourceResult[]> {
  const response = await fetch(`${API_BASE}/explorer/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      date_range: dateRange || null,
      fachbereich: filters?.fachbereich || null,
      document_type: filters?.document_type || null,
    }),
  });
  if (!response.ok) {
    throw new Error(`Quellensuche fehlgeschlagen (HTTP ${response.status})`);
  }
  const data = await response.json();
  return data.sources;
}

/** UC#10: Answer a Fachfrage */
export async function answerQuestion(
  query: string,
  dateRange?: DateRange,
  topK: number = 10,
  filters?: ExplorerFilters,
  systemPrompt?: string | null,
): Promise<GeneratedAnswerResult> {
  const response = await fetch(`${API_BASE}/explorer/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      date_range: dateRange || null,
      top_k: topK,
      fachbereich: filters?.fachbereich || null,
      document_type: filters?.document_type || null,
      system_prompt: systemPrompt || null,
    }),
  });
  if (!response.ok) {
    throw new Error(`Fachfrage fehlgeschlagen (HTTP ${response.status})`);
  }
  return response.json();
}

/** UC#2: Generate topic overview */
export async function generateOverview(
  query: string,
  dateRange?: DateRange,
  topK: number = 10,
  filters?: ExplorerFilters,
  systemPrompt?: string | null,
): Promise<GeneratedAnswerResult> {
  const response = await fetch(`${API_BASE}/explorer/overview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query,
      date_range: dateRange || null,
      top_k: topK,
      fachbereich: filters?.fachbereich || null,
      document_type: filters?.document_type || null,
      system_prompt: systemPrompt || null,
    }),
  });
  if (!response.ok) {
    throw new Error(`Themenüberblick fehlgeschlagen (HTTP ${response.status})`);
  }
  return response.json();
}
