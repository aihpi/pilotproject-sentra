import { useState } from "react";

import {
  answerQuestion,
  findExternalSources,
  findSimilarDocuments,
  generateOverview,
  searchDocumentsByTopic,
} from "@/lib/api";
import type { ResultData, SubMode } from "./types";

interface DateRange {
  date_from?: string | null;
  date_to?: string | null;
}

interface Filters {
  fachbereich?: string | null;
  document_type?: string | null;
}

interface SearchRequest {
  query: string;
  subMode: SubMode;
  dateRange?: DateRange;
  filters?: Filters;
  /** Edited prompt for this sub-mode, or null to let the server use its own
   *  default. Only the generating sub-modes have one. */
  customPrompt?: string | null;
}

/** Which call each sub-mode makes, and what came back.
 *
 * Separated from the view because it is the one piece here that is not
 * markup: five sub-modes, five endpoints, three result shapes, one loading
 * flag and one error string. The component below it renders states; this
 * decides what they are.
 */
export function useExplorerSearch() {
  const [isLoading, setIsLoading] = useState(false);
  const [result, setResult] = useState<ResultData | null>(null);
  const [error, setError] = useState<string | null>(null);

  /** Drop whatever is on screen. Used when switching tab or sub-mode, where
   *  a result from the previous mode would be answering a question the user
   *  can no longer see. */
  function clear() {
    setResult(null);
    setError(null);
  }

  async function search({
    query,
    subMode,
    dateRange,
    filters,
    customPrompt,
  }: SearchRequest) {
    if (!query.trim()) return;
    setIsLoading(true);
    setResult(null);
    setError(null);

    try {
      switch (subMode) {
        case "thema": {
          const docs = await searchDocumentsByTopic(query, dateRange, 20, filters);
          setResult({ type: "documents", documents: docs });
          break;
        }
        case "aehnliche": {
          // Takes no filters: the query names one document and the server
          // finds documents like it.
          const docs = await findSimilarDocuments(query);
          setResult({ type: "documents", documents: docs, referenceDoc: query });
          break;
        }
        case "quellen": {
          const sources = await findExternalSources(query, dateRange, filters);
          setResult({ type: "sources", sources });
          break;
        }
        case "fachfrage": {
          const answer = await answerQuestion(query, dateRange, 10, filters, customPrompt);
          setResult({ type: "answer", result: answer, query });
          break;
        }
        case "ueberblick": {
          const answer = await generateOverview(query, dateRange, 10, filters, customPrompt);
          setResult({ type: "answer", result: answer, query });
          break;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ein Fehler ist aufgetreten.");
    } finally {
      setIsLoading(false);
    }
  }

  return { isLoading, result, error, search, clear, setError };
}
