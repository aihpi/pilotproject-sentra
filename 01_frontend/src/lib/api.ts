import type {
  QueryRequest,
  SourceResponse,
  IngestResponse,
  DocumentInfo,
  FeedbackRequest,
  HealthResponse,
} from "@/types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "/api";

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
