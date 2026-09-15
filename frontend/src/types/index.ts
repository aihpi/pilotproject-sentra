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
  /** Indexed documents with no matching file on disk. */
  stale_documents: string[];
}

/** One Referat offered in the Fachbereich filter. */
export interface ReferatOption {
  /** The value to filter on. fachbereich_number is the indexed field. */
  number: string;
  /** Label only. Comes from the backend mapping, not from the documents,
   *  whose own Fachbereich names are inconsistent. */
  name: string;
}

/** Prompts and filter options, served by GET /api/config.
 *  Previously hardcoded in ExplorerView with a comment asking whoever edited
 *  them to keep both copies in step. */
export interface AppConfig {
  /** Keyed by question sub-mode id: fachfrage, ueberblick. */
  prompts: Record<string, string>;
  document_types: string[];
  referate: ReferatOption[];
}
