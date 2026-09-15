import { AlertCircle, Loader2 } from "lucide-react";

import { DocumentList } from "./DocumentList";
import { GeneratedAnswer } from "./GeneratedAnswer";
import { SourceUrlList } from "./SourceUrlList";
import type { ResultData } from "./types";

interface ResultPanelProps {
  isLoading: boolean;
  error: string | null;
  result: ResultData | null;
}

/** Whatever the search area is currently producing: a spinner, an error, or
 *  one of the three result shapes.
 *
 * The order matters. Loading wins over a previous result so a stale list is
 * not shown as though it answered the new query, and an error wins over a
 * result for the same reason.
 */
export function ResultPanel({ isLoading, error, result }: ResultPanelProps) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-6 w-6 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">Suche läuft…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="flex flex-col items-center gap-3 text-center">
          <AlertCircle className="h-6 w-6 text-destructive" />
          <p className="text-sm text-destructive">{error}</p>
        </div>
      </div>
    );
  }

  if (!result) return null;

  switch (result.type) {
    case "documents":
      return (
        <DocumentList documents={result.documents} referenceDoc={result.referenceDoc} />
      );
    case "answer":
      return <GeneratedAnswer result={result.result} query={result.query} />;
    case "sources":
      return <SourceUrlList sources={result.sources} />;
  }
}
