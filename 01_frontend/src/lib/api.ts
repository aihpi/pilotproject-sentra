import type {
  QueryRequest,
  SourceResponse,
  IngestResponse,
  DocumentInfo,
  FeedbackRequest,
  HealthResponse,
  DocumentResult,
  GeneratedAnswerResult,
  ExternalSourceResult,
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

export async function streamQuery(
  request: QueryRequest,
  callbacks: {
    onToken: (token: string) => void;
    onSources: (sources: SourceResponse[]) => void;
    onDone: () => void;
    onError: (error: string) => void;
  },
): Promise<void> {
  const response = await fetch(`${API_BASE}/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({
      question: request.question,
      fachbereich: request.fachbereich || undefined,
      document_type: request.document_type || undefined,
      top_k: request.top_k || 10,
    }),
  });

  if (!response.ok) {
    throw new Error(`Anfrage fehlgeschlagen (HTTP ${response.status})`);
  }

  const reader = response.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const messages = buffer.split("\n\n");
      buffer = messages.pop() || "";

      for (const message of messages) {
        if (!message.trim()) continue;

        const lines = message.split("\n");
        let eventType = "";
        let data = "";

        for (const line of lines) {
          if (line.startsWith("event:")) {
            eventType = line.substring(6).trim();
          } else if (line.startsWith("data:")) {
            data = line.substring(5).trim();
          }
        }

        if (!eventType || !data) continue;

        switch (eventType) {
          case "sources":
            callbacks.onSources(JSON.parse(data));
            break;
          case "token": {
            const { text } = JSON.parse(data);
            callbacks.onToken(text);
            break;
          }
          case "done":
            callbacks.onDone();
            return;
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export async function fetchDocuments(): Promise<DocumentInfo[]> {
  const response = await fetch(`${API_BASE}/documents`);
  if (!response.ok) {
    throw new Error(`Dokumente konnten nicht geladen werden (HTTP ${response.status})`);
  }
  return response.json();
}

export async function ingestDocuments(): Promise<IngestResponse> {
  const response = await fetch(`${API_BASE}/ingest`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Ingestion fehlgeschlagen (HTTP ${response.status})`);
  }
  return response.json();
}

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
