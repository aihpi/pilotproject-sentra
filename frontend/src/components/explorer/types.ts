import type { DocumentResult, ExternalSourceResult, GeneratedAnswerResult } from "@/types";

/** The two things the explorer does: find documents, or answer about them. */
export type Tab = "dokumente" | "fragen";

export type DocSubMode = "thema" | "aehnliche" | "quellen";

/** The generating modes. These ids are also the keys of the prompts served by
 *  GET /api/config, so they are part of the API contract. */
export type FragenSubMode = "fachfrage" | "ueberblick";

export type SubMode = DocSubMode | FragenSubMode;

export interface SubModeConfig {
  id: SubMode;
  label: string;
  icon: React.ReactNode;
  placeholder: string;
  description: string;
}

/** What a finished search produced. The shape says which component renders it.
 *
 *  The answer variant carries its query because feedback is recorded against
 *  the question that produced the answer, and by the time a rating is sent the
 *  input may hold something else entirely.
 */
export type ResultData =
  | { type: "documents"; documents: DocumentResult[]; referenceDoc?: string }
  | { type: "answer"; result: GeneratedAnswerResult; query: string }
  | { type: "sources"; sources: ExternalSourceResult[] };
