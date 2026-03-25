export interface DocumentInfo {
  aktenzeichen: string;
  title: string;
  fachbereich_number: string;
  fachbereich: string;
  document_type: string;
  completion_date: string;
  language: string;
  source_file: string;
}

export interface FeedbackRequest {
  question: string;
  answer: string;
  rating: "positive" | "negative";
  comment?: string | null;
}

export interface HealthResponse {
  status: string;
  qdrant: string;
  collection?: Record<string, unknown> | null;
}

// --- Explorer view types ---

export interface DocumentResult {
  aktenzeichen: string;
  title: string;
  fachbereich: string;
  document_type: string;
  completion_date: string;
  relevance_score: number;
  source_file?: string;
}

export interface GeneratedAnswerResult {
  text: string;
  sources: {
    aktenzeichen: string;
    title: string;
    fachbereich: string;
    completion_date: string;
    source_file?: string;
  }[];
  system_prompt?: string | null;
}

export interface ExternalSourceResult {
  url: string;
  label: string;
  context: string;
  cited_in: {
    aktenzeichen: string;
    title: string;
  }[];
}

// --- Ingestion types ---

export interface IngestionStatus {
  status: "idle" | "running" | "completed" | "failed";
  total_files: number;
  processed: number;
  skipped: number;
  chunks_created: number;
  errors: string[];
  current_file: string;
  started_at: string | null;
  completed_at: string | null;
}
