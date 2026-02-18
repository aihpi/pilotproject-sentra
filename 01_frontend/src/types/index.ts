export interface QueryRequest {
  question: string;
  fachbereich?: string | null;
  document_type?: string | null;
  top_k?: number;
}

export interface SourceResponse {
  aktenzeichen: string;
  title: string;
  section_title: string;
  fachbereich: string;
  score: number;
  text_preview: string;
  source_file: string;
}

export interface QueryResponse {
  answer: string;
  sources: SourceResponse[];
}

export interface IngestResponse {
  documents_processed: number;
  chunks_created: number;
  errors: string[];
}

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
